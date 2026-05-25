#!/usr/bin/env python3
"""Offline Daily Section C artifact gate preview.

Reads a local inbox JSON (``news_inbox.json`` by default) and a
caller-supplied artifact directory, converts each inbox row into a
minimal card, and runs the Daily artifact gate
(:func:`routes.daily_artifact_gate.filter_daily_section_c_cards`)
to produce an admitted / held-for-review split — without starting
the FastAPI server and without touching the live ``artifacts/``
directory.

This is the missing offline step between the quality diagnostic
(which shows ``artifact_present`` / ``artifact_fields_complete``)
and the live ``/movers/today?artifact_gate=true`` route.  The
preview lets the operator see the gate verdict against a staging
artifact directory before copying artifacts to production.

Read-only by construction
-------------------------

* No DB reads or writes.
* No ``yfinance``, ``market_data``, paid provider, LLM, or FastAPI
  surface (never imports ``api`` or ``routes.movers``).
* No mutation of ``news_inbox.json``, the events DB, the news cache,
  or any artifact file.  The gate function itself is read-only — it
  opens artifact files in read mode only and never writes.
* The only import from ``routes/`` is the pure-function gate module
  ``routes.daily_artifact_gate``, which has no FastAPI dependency.

Conservative wording
--------------------

Banned tokens in any prose this script emits: ``proof``, ``proven``,
``validated``, ``automatically``, ``alpha generated``, ``guaranteed``,
``correct ticker``.  The script never claims a card is validated or
should be admitted; the gate's binary verdict is descriptive only.

Usage::

    # Preview against a staging artifact directory:
    python scripts/daily_artifact_gate_preview.py \
        --input news_inbox.json \
        --artifact-dir staging/artifacts/ \
        --json

    # Preview against the default news_inbox.json:
    python scripts/daily_artifact_gate_preview.py \
        --artifact-dir staging/artifacts/

Output contract (JSON)::

    {
      "ok":                     bool,
      "artifact_type":          "daily_artifact_gate_preview",
      "input_path":             str,
      "artifact_dir":           str,
      "total_cards":            int,
      "admitted_count":         int,
      "held_for_review_count":  int,
      "gate_id":                str,
      "admitted":               [card, ...],
      "held_for_review":        [card, ...],
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

Each card in ``admitted`` and ``held_for_review`` carries at least::

    {
      "candidate_id":  str | null,
      "headline":      str,
      "source":        str | null,
      "published_at":  str | null,
    }
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.daily_artifact_gate import (  # noqa: E402
    GATE_ID,
    filter_daily_section_c_cards,
)


_ARTIFACT_TYPE: str = "daily_artifact_gate_preview"
_DEFAULT_INPUT_PATH: str = "news_inbox.json"


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_inbox(input_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Load inbox rows from a JSON file.

    Returns ``(rows, errors)``.  Accepts a top-level list of dicts
    or a mapping with a ``"candidates"`` key holding such a list.
    """
    p = Path(input_path)
    if not p.exists():
        return [], [f"--input file does not exist: {input_path}"]
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return [], [f"failed to read --input {input_path}: {e}"]
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"failed to parse --input JSON {input_path}: {e}"]

    if isinstance(raw, list):
        rows_raw = raw
    elif isinstance(raw, dict):
        rows_raw = raw.get("candidates")
        if not isinstance(rows_raw, list):
            return [], [
                "--input JSON mapping has no 'candidates' list at "
                "top level; expected either a top-level list or "
                "{candidates: [...]}"
            ]
    else:
        return [], [
            f"--input JSON top level is not a list or mapping "
            f"(got {type(raw).__name__})"
        ]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, entry in enumerate(rows_raw):
        if not isinstance(entry, dict):
            errors.append(
                f"--input JSON row {i} is not a mapping "
                f"(got {type(entry).__name__})"
            )
            continue
        rows.append(dict(entry))
    return rows, errors


# ---------------------------------------------------------------------------
# Row → card conversion
# ---------------------------------------------------------------------------


def _inbox_row_to_card(row: dict[str, Any]) -> dict[str, Any]:
    """Convert an inbox row into a minimal card the gate can evaluate.

    The gate checks ``card['candidate_id']`` — everything else is
    pass-through context for the operator.  ``title`` is mapped to
    ``headline`` when the row uses the news_inbox.json field name.
    """
    card: dict[str, Any] = {}
    cid = row.get("candidate_id")
    if cid is not None:
        card["candidate_id"] = cid
    card["headline"] = row.get("headline") or row.get("title") or ""
    card["source"] = row.get("source")
    card["published_at"] = row.get("published_at")
    return card


# ---------------------------------------------------------------------------
# Core preview logic
# ---------------------------------------------------------------------------


def run_preview(
    *,
    input_path: str,
    artifact_dir: str,
) -> dict[str, Any]:
    """Run the gate preview and return the envelope.

    Pure function — the gate reads artifact files in read-only mode
    and never mutates the filesystem.
    """
    warnings: list[str] = []
    errors: list[str] = []

    rows, load_errors = _load_inbox(input_path)
    errors.extend(load_errors)

    artifact_path = Path(artifact_dir)
    if not artifact_path.is_dir():
        errors.append(
            f"--artifact-dir does not exist or is not a directory: "
            f"{artifact_dir}"
        )
        return {
            "ok":                    False,
            "artifact_type":         _ARTIFACT_TYPE,
            "input_path":            input_path,
            "artifact_dir":          artifact_dir,
            "total_cards":           0,
            "admitted_count":        0,
            "held_for_review_count": 0,
            "gate_id":              GATE_ID,
            "admitted":              [],
            "held_for_review":       [],
            "warnings":              warnings,
            "errors":                errors,
        }

    cards = [_inbox_row_to_card(r) for r in rows]

    admitted, meta = filter_daily_section_c_cards(
        cards, artifact_dir=artifact_path,
    )

    admitted_set = set(id(c) for c in admitted)
    held = [c for c in cards if id(c) not in admitted_set]

    if not rows:
        warnings.append(
            "no rows loaded from --input; the preview has nothing "
            "to evaluate."
        )

    envelope: dict[str, Any] = {
        "ok":                    not errors,
        "artifact_type":         _ARTIFACT_TYPE,
        "input_path":            input_path,
        "artifact_dir":          artifact_dir,
        "total_cards":           len(cards),
        "admitted_count":        meta["admitted_count"],
        "held_for_review_count": meta["held_for_review_count"],
        "gate_id":               meta["gate_id"],
        "admitted":              admitted,
        "held_for_review":       held,
        "warnings":              warnings,
        "errors":                errors,
    }
    return envelope


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline Daily Section C artifact gate preview.  Reads a "
            "local inbox JSON and a staging artifact directory, runs "
            "the gate, and prints the admitted / held-for-review "
            "split.  No DB, no provider, no yfinance, no LLM, no "
            "FastAPI server required."
        ),
    )
    parser.add_argument(
        "--input", dest="input_path", default=_DEFAULT_INPUT_PATH,
        help=(
            "Path to the inbox JSON file to preview.  Defaults to "
            f"{_DEFAULT_INPUT_PATH!r}."
        ),
    )
    parser.add_argument(
        "--artifact-dir", dest="artifact_dir", required=True,
        help=(
            "Directory of analyzed_event_artifact_<cid>.json files "
            "to evaluate against.  Required — the preview does not "
            "default to the live artifacts/ directory."
        ),
    )
    parser.add_argument(
        "--json", dest="json_flag", action="store_true",
        help=(
            "Emit structured JSON (this is also the default — kept "
            "for symmetry with sibling read-only scripts)."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    envelope = run_preview(
        input_path=args.input_path,
        artifact_dir=args.artifact_dir,
    )
    print(_render_json(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_preview",
    "main",
)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

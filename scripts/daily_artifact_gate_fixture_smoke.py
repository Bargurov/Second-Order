#!/usr/bin/env python3
"""Daily artifact-gate fixture smoke.

Read-only fixture smoke that proves the Daily Section C artifact
gate (:mod:`routes.daily_artifact_gate`) can produce one admitted
candidate and one held-for-review candidate against a fresh temp
artifact directory the smoke owns end-to-end.

The smoke is deliberately tiny: it builds a single
``tempfile.TemporaryDirectory``, writes one well-formed
``analyzed_event_artifact_<candidate_id>.json`` into it, runs
:func:`routes.daily_artifact_gate.filter_daily_section_c_cards`
on two synthetic Daily cards (one whose ``candidate_id`` matches
the artifact and one whose does not), and reports the verdict.

Read-only by construction
-------------------------

* No DB reads, no DB writes.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM,
  or paid provider call.  No network access.
* No FastAPI surface — never imports ``api`` or ``routes`` other
  than the gate predicate itself.
* The smoke never reads or writes the real ``artifacts/``
  directory.  The temp dir is created and torn down inside the
  call; nothing leaks out.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.  The script refuses to overwrite an existing
  file at the supplied output path.

Output contract (JSON)::

    {
      "ok":                     bool,
      "candidates_checked":     int,
      "admitted_count":         int,
      "held_for_review_count":  int,
      "admitted_candidates":    [str, ...],
      "held_candidates":        [str, ...],
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

The envelope carries EXACTLY these 8 keys.

Conservative wording
--------------------

The smoke surfaces a candidate as "admitted" when the gate
returns it and "held for review" when the gate filters it out;
it never claims the gate is correct, the artifact is reviewed,
or the candidate is fit to trade.  Banned tokens (``proof``,
``proven``, ``guaranteed``, ``automatically``, ``validated``,
``alpha generated``, ``correct ticker``, ``definitely``,
``approved``, ``production ready``, ``demo_ready``) never appear
in any text or JSON the smoke emits.

Usage::

    python scripts/daily_artifact_gate_fixture_smoke.py
    python scripts/daily_artifact_gate_fixture_smoke.py --json
    python scripts/daily_artifact_gate_fixture_smoke.py --json \\
        --output /tmp/daily_artifact_gate_fixture_smoke.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.daily_artifact_gate import (  # noqa: E402
    filter_daily_section_c_cards,
)


# Two synthetic candidates.  The admit fixture has a matching
# artifact file written into the temp dir; the held fixture has
# no artifact and is therefore held for review.
_ADMIT_CANDIDATE_ID: str = "fixture-admit-001"
_HELD_CANDIDATE_ID:  str = "fixture-held-001"


# Pure-fixture artifact body — non-empty strings on the three
# fields the gate enforces.  The values are illustrative only and
# are never resolved against any real ticker universe.
_FIXTURE_ARTIFACT_BODY: dict[str, Any] = {
    "mechanism_family":  "supply_shock",
    "primary_ticker":    "FIXTURE_PRIMARY",
    "benchmark_ticker":  "FIXTURE_BENCHMARK",
}


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_daily_artifact_gate_fixture_smoke() -> dict[str, Any]:
    """Build a fresh temp artifact dir, exercise the gate on two
    synthetic Daily cards, and return the 8-key envelope.

    The temp dir is owned by this function — it is created at the
    start of the call and removed at the end.  No file outside
    Python's tempdir is read or written.  The real ``artifacts/``
    directory is never opened.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    cards = [
        {
            "candidate_id": _ADMIT_CANDIDATE_ID,
            "headline":     "fixture admit card",
        },
        {
            "candidate_id": _HELD_CANDIDATE_ID,
            "headline":     "fixture held card",
        },
    ]

    admitted_ids: list[str] = []
    held_ids:     list[str] = []

    try:
        with tempfile.TemporaryDirectory(
            prefix="daily_artifact_gate_fixture_smoke_",
        ) as tmp:
            artifact_dir = Path(tmp)
            artifact_path = (
                artifact_dir
                / f"analyzed_event_artifact_{_ADMIT_CANDIDATE_ID}.json"
            )
            artifact_path.write_text(
                json.dumps(_FIXTURE_ARTIFACT_BODY),
                encoding="utf-8",
            )

            admitted, _meta = filter_daily_section_c_cards(
                cards, artifact_dir=artifact_dir,
            )
            admitted_ids = [
                c.get("candidate_id", "")
                for c in admitted
                if isinstance(c, dict)
            ]
            admitted_set = set(admitted_ids)
            held_ids = [
                c["candidate_id"]
                for c in cards
                if c["candidate_id"] not in admitted_set
            ]
    except OSError as e:
        errors.append(f"temp artifact dir setup failed: {e}")

    candidates_checked = len(cards)
    admitted_count = len(admitted_ids)
    held_for_review_count = len(held_ids)

    expected_admit = (
        admitted_ids == [_ADMIT_CANDIDATE_ID]
        and held_ids == [_HELD_CANDIDATE_ID]
    )
    if not expected_admit and not errors:
        errors.append(
            "fixture smoke did not produce the expected "
            "one-admitted / one-held outcome"
        )

    ok = not errors

    return {
        "ok":                    ok,
        "candidates_checked":    candidates_checked,
        "admitted_count":        admitted_count,
        "held_for_review_count": held_for_review_count,
        "admitted_candidates":   admitted_ids,
        "held_candidates":       held_ids,
        "warnings":              warnings,
        "errors":                errors,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Daily artifact-gate fixture smoke", ""]
    lines.append(f"OK:                  {report['ok']}")
    lines.append(f"Candidates checked:  {report['candidates_checked']}")
    lines.append(
        f"Admitted:            {report['admitted_count']} "
        f"({', '.join(report['admitted_candidates']) or '-'})"
    )
    lines.append(
        f"Held for review:     {report['held_for_review_count']} "
        f"({', '.join(report['held_candidates']) or '-'})"
    )
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
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
            "Read-only Daily artifact-gate fixture smoke.  Builds a "
            "fresh temp artifact directory, writes one valid "
            "analyzed_event_artifact_<cid>.json into it, runs the "
            "Daily Section C artifact gate on two synthetic cards, "
            "and reports one admitted / one held-for-review.  "
            "Never touches the real artifacts directory; never "
            "opens a DB, provider, LLM, or FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text view.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the smoke has no filesystem side effect "
            "outside Python's tempdir.  Refuses to overwrite an "
            "existing file."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _write_output(*, envelope: dict[str, Any], output_path: str) -> str | None:
    """Write the JSON envelope to ``output_path``.  Returns an
    error string when the path already exists or the write fails;
    returns ``None`` on success.  The smoke refuses to overwrite
    an existing file so an operator never loses a prior run by
    mistake.
    """
    p = Path(output_path)
    if p.exists():
        return (
            f"--output path already exists; refusing to overwrite: "
            f"{output_path}"
        )
    try:
        p.write_text(_render_json(envelope), encoding="utf-8")
    except OSError as e:
        return f"failed to write --output {output_path}: {e}"
    return None


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = run_daily_artifact_gate_fixture_smoke()

    if args.output_path:
        write_err = _write_output(
            envelope=report, output_path=args.output_path,
        )
        if write_err:
            report["errors"].append(write_err)
            report["ok"] = False

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_daily_artifact_gate_fixture_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

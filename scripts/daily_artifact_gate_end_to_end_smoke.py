#!/usr/bin/env python3
"""Daily artifact-gate end-to-end fixture smoke.

Read-only end-to-end smoke that exercises the full Daily Section C
artifact-gate path against a temp artifact directory the smoke
owns.  It uses the SAME helper
(:func:`routes.daily_artifact_gate.filter_daily_section_c_cards`)
that the ``/movers/today`` route invokes — never a parallel
reimplementation — and reports whether the gate admitted the one
artifact-backed candidate and held the one unenriched candidate
exactly as designed.

The smoke also hashes the real ``artifacts/`` directory and the
real ``news_inbox.json`` file before and after the run and
surfaces a single ``real_files_unchanged`` boolean so the
operator can confirm the smoke did not touch shared inputs even
by accident.

Read-only by construction
-------------------------

* No DB reads, no DB writes.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM,
  or paid provider call.  No network access.
* No FastAPI surface — never imports ``api`` or ``routes``
  modules other than the gate predicate itself.
* Real ``artifacts/`` directory and real ``news_inbox.json`` are
  never opened for writes; both are hashed read-only before and
  after the run and any mismatch is surfaced as an error.
* ``--output`` is the only path the smoke ever writes to, and
  only when explicitly passed.  The script refuses to overwrite
  an existing file at the supplied output path.

Output contract (JSON)::

    {
      "ok":                     bool,
      "candidates_checked":     int,
      "admitted_count":         int,
      "held_for_review_count":  int,
      "admitted_candidates":    [
        {
          "candidate_id":     str,
          "mechanism_family": str,
          "primary_ticker":   str,
          "benchmark_ticker": str,
        }, ...
      ],
      "held_candidates":        [
        {"candidate_id": str, "hold_reason": str}, ...
      ],
      "real_files_unchanged":   bool,
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

The envelope carries EXACTLY these 9 keys.

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

    python scripts/daily_artifact_gate_end_to_end_smoke.py
    python scripts/daily_artifact_gate_end_to_end_smoke.py --json
    python scripts/daily_artifact_gate_end_to_end_smoke.py --json \\
        --output /tmp/daily_artifact_gate_end_to_end_smoke.json
"""
from __future__ import annotations

import argparse
import hashlib
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


# Real shared inputs the smoke must NOT mutate.  Hashed read-only
# before and after the smoke runs so the operator sees a single
# bool instead of a stitched-together inference.
_REAL_ARTIFACTS_DIR: Path = ROOT / "artifacts"
_REAL_NEWS_INBOX:    Path = ROOT / "news_inbox.json"


# Two synthetic candidates.  The admit fixture has a matching
# artifact file written into the temp dir; the held fixture has
# no artifact and is therefore held for review.
_ADMIT_CANDIDATE_ID: str = "fixture-admit-end-to-end-001"
_HELD_CANDIDATE_ID:  str = "fixture-held-end-to-end-001"


# Pure-fixture artifact body — non-empty strings on the three
# fields the gate enforces.  Values are illustrative only; they
# are never resolved against any real ticker universe.
_FIXTURE_ARTIFACT_BODY: dict[str, Any] = {
    "mechanism_family":  "supply_shock",
    "primary_ticker":    "FIXTURE_PRIMARY",
    "benchmark_ticker":  "FIXTURE_BENCHMARK",
}


_HOLD_REASON_NO_ARTIFACT: str = (
    "no analyzed_event_artifact_<candidate_id>.json on the temp "
    "artifact directory; the gate holds the row for operator review"
)


# ---------------------------------------------------------------------------
# Real-file integrity helpers — read-only
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str | None:
    """Return the sha256 hex digest of ``path``, or ``None`` when
    the file does not exist.  Read-only.
    """
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _hash_dir(root: Path) -> dict[str, str] | None:
    """Return a ``{relpath: sha256}`` snapshot of every file under
    ``root``, or ``None`` when ``root`` is not a directory.
    Read-only.
    """
    if not root.is_dir():
        return None
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            digest = _hash_file(p)
            if digest is not None:
                out[str(p.relative_to(root))] = digest
    return out


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_daily_artifact_gate_end_to_end_smoke() -> dict[str, Any]:
    """Build a fresh temp artifact dir, exercise the production
    Daily artifact-gate helper on two synthetic cards, and return
    the 9-key envelope.

    The smoke hashes the real ``artifacts/`` directory and real
    ``news_inbox.json`` file before and after the run.  A single
    ``real_files_unchanged`` bool surfaces in the envelope; an
    error is appended when either snapshot drifts.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    artifacts_before  = _hash_dir(_REAL_ARTIFACTS_DIR)
    news_inbox_before = _hash_file(_REAL_NEWS_INBOX)

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

    admitted_items: list[dict[str, Any]] = []
    held_items:     list[dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory(
            prefix="daily_artifact_gate_end_to_end_smoke_",
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

            admitted_ids: set[str] = set()
            for card in admitted:
                if not isinstance(card, dict):
                    continue
                cid = card.get("candidate_id")
                if not isinstance(cid, str) or not cid.strip():
                    continue
                admitted_ids.add(cid)
                doc = _read_artifact_for_admitted(artifact_dir, cid)
                admitted_items.append({
                    "candidate_id":     cid,
                    "mechanism_family": _str_field(doc, "mechanism_family"),
                    "primary_ticker":   _str_field(doc, "primary_ticker"),
                    "benchmark_ticker": _str_field(doc, "benchmark_ticker"),
                })

            for card in cards:
                cid = card.get("candidate_id", "")
                if not isinstance(cid, str) or cid in admitted_ids:
                    continue
                held_items.append({
                    "candidate_id": cid,
                    "hold_reason":  _HOLD_REASON_NO_ARTIFACT,
                })
    except OSError as e:
        errors.append(f"temp artifact dir setup failed: {e}")

    artifacts_after  = _hash_dir(_REAL_ARTIFACTS_DIR)
    news_inbox_after = _hash_file(_REAL_NEWS_INBOX)
    real_files_unchanged = (
        artifacts_before == artifacts_after
        and news_inbox_before == news_inbox_after
    )
    if not real_files_unchanged:
        errors.append(
            "real artifacts/ or news_inbox.json bytes changed during "
            "the smoke run — investigate before relying on the verdict"
        )

    candidates_checked    = len(cards)
    admitted_count        = len(admitted_items)
    held_for_review_count = len(held_items)

    expected_outcome = (
        admitted_count == 1
        and held_for_review_count == 1
        and {i["candidate_id"] for i in admitted_items}
            == {_ADMIT_CANDIDATE_ID}
        and {i["candidate_id"] for i in held_items}
            == {_HELD_CANDIDATE_ID}
    )
    if not expected_outcome and not errors:
        errors.append(
            "end-to-end smoke did not produce the expected "
            "one-admitted / one-held outcome"
        )

    ok = not errors

    return {
        "ok":                    ok,
        "candidates_checked":    candidates_checked,
        "admitted_count":        admitted_count,
        "held_for_review_count": held_for_review_count,
        "admitted_candidates":   admitted_items,
        "held_candidates":       held_items,
        "real_files_unchanged":  real_files_unchanged,
        "warnings":              warnings,
        "errors":                errors,
    }


def _read_artifact_for_admitted(
    artifact_dir: Path, candidate_id: str,
) -> dict[str, Any]:
    """Read the temp artifact for an admitted candidate.  Returns
    an empty dict on any read or parse failure — the gate already
    validated the artifact, so this re-read only enriches the
    admitted item; it never overrides the gate's verdict.
    """
    p = artifact_dir / f"analyzed_event_artifact_{candidate_id}.json"
    if not p.is_file():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _str_field(doc: dict[str, Any], field: str) -> str:
    value = doc.get(field)
    return value if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_admitted(item: dict[str, Any]) -> str:
    return (
        f"{item.get('candidate_id', '')} "
        f"[mechanism_family={item.get('mechanism_family', '')}, "
        f"primary_ticker={item.get('primary_ticker', '')}, "
        f"benchmark_ticker={item.get('benchmark_ticker', '')}]"
    )


def _fmt_held(item: dict[str, Any]) -> str:
    return (
        f"{item.get('candidate_id', '')} "
        f"[hold_reason={item.get('hold_reason', '')}]"
    )


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Daily artifact-gate end-to-end smoke", ""]
    lines.append(f"OK:                    {report['ok']}")
    lines.append(f"Candidates checked:    {report['candidates_checked']}")
    lines.append(f"Admitted:              {report['admitted_count']}")
    for item in report["admitted_candidates"]:
        lines.append(f"  - {_fmt_admitted(item)}")
    lines.append(f"Held for review:       {report['held_for_review_count']}")
    for item in report["held_candidates"]:
        lines.append(f"  - {_fmt_held(item)}")
    lines.append(f"Real files unchanged:  {report['real_files_unchanged']}")
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
            "Read-only Daily artifact-gate end-to-end fixture smoke. "
            "Builds a fresh temp artifact directory, writes one valid "
            "analyzed_event_artifact_<cid>.json into it, runs the "
            "same Daily Section C gate helper the /movers/today route "
            "calls, and reports one admitted / one held with the "
            "artifact-backed fields surfaced for the admitted row.  "
            "Real artifacts directory and real news_inbox.json are "
            "hashed before and after the run; any drift is surfaced "
            "as an error.  Never opens a DB, provider, LLM, or "
            "FastAPI surface."
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

    report = run_daily_artifact_gate_end_to_end_smoke()

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
    "run_daily_artifact_gate_end_to_end_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

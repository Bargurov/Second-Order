#!/usr/bin/env python3
"""Daily reviewed-artifact end-to-end fixture smoke.

Read-only end-to-end smoke that proves the operator-reviewed Daily
Section C path works against temp files only:

  reviewed worksheet row  →  emitter  →  analyzed_event_artifact
                          →  artifact-backed card source
                          →  routes.daily_artifact_gate.filter_daily_section_c_cards
                          →  admitted card

The smoke writes everything inside a single
``tempfile.TemporaryDirectory`` it owns and never opens the
operator's real ``artifacts/`` directory or real
``news_inbox.json`` for writes.  Both shared inputs are hashed
read-only before and after the run; any drift surfaces under
``real_files_unchanged`` as a hard error.

The same Daily gate helper that ``/movers/today`` calls in
production
(:func:`routes.daily_artifact_gate.filter_daily_section_c_cards`)
is invoked here — never a parallel reimplementation.  The emitter
import is wrapped in a thin lazy seam so tests can patch the
emitter directly and the smoke's top-level import surface stays
narrow.

Read-only by construction
-------------------------

* No DB reads, no DB writes.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM,
  or paid provider call.  No network access.
* No FastAPI surface — never imports ``api`` or other ``routes``
  modules besides the gate predicate itself.
* Real ``artifacts/`` directory and real ``news_inbox.json`` are
  never opened for writes; both are hashed read-only before and
  after the run and any mismatch is surfaced as an error.
* ``--output`` is the only path the smoke ever writes to outside
  Python's tempdir, and only when explicitly passed.  The script
  refuses to overwrite an existing file at the supplied output
  path.
* No ``candidate_id`` auto-generation: the operator-supplied
  ``daily-demo-001`` flows from the CSV row to the artifact
  filename to the admitted card unchanged.

Output contract (JSON)::

    {
      "ok":                     bool,
      "worksheet_rows":         int,
      "artifacts_written":      int,
      "cards_loaded":           int,
      "admitted_count":         int,
      "held_for_review_count":  int,
      "admitted_candidates":    [
        {
          "candidate_id":     str,
          "headline":         str,
          "mechanism_family": str,
          "primary_ticker":   str,
          "benchmark_ticker": str,
        }, ...
      ],
      "real_files_unchanged":   bool,
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

The envelope carries EXACTLY these 10 keys.

Conservative wording
--------------------

The smoke surfaces a candidate as "admitted" when the gate
returns it and "held for review" when the gate filters it out;
it never claims the gate is correct, the artifact is reviewed,
or the candidate is fit to trade.  Banned tokens (``proof``,
``proven``, ``guaranteed``, ``automatically``, ``validated``,
``alpha generated``, ``correct ticker``, ``definitely``,
``approved``, ``production ready``, ``demo_ready``,
``demo-ready``) never appear in any text or JSON the smoke
emits.

Usage::

    python scripts/daily_reviewed_artifact_end_to_end_smoke.py
    python scripts/daily_reviewed_artifact_end_to_end_smoke.py --json
    python scripts/daily_reviewed_artifact_end_to_end_smoke.py --json \\
        --output /tmp/daily_reviewed_artifact_end_to_end_smoke.json
"""
from __future__ import annotations

import argparse
import csv
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


# Operator-pinned candidate_ids.  The smoke never auto-generates a
# candidate_id — the included row's value flows from the CSV to the
# artifact filename to the admitted card unchanged.
_INCLUDED_CANDIDATE_ID: str = "daily-demo-001"
_EXCLUDED_CANDIDATE_ID: str = "daily-demo-excluded-002"


# CSV header the emitter expects (10 columns).  Mirrors the schema
# documented in :mod:`scripts.daily_analyzed_event_artifact_emitter`.
_WORKSHEET_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "inclusion_reason",
    "operator_notes",
    "include_in_daily_section_c",
)


# Fixture rows the smoke writes into its temp CSV.  Values are
# illustrative only and never resolved against any real ticker
# universe.
_INCLUDED_ROW: dict[str, str] = {
    "candidate_id":               _INCLUDED_CANDIDATE_ID,
    "headline":                   "Reviewed Daily candidate fixture",
    "event_date":                 "2026-05-15",
    "mechanism_family":           "supply_shock",
    "primary_ticker":             "FIXTURE_PRIMARY",
    "benchmark_ticker":           "FIXTURE_BENCHMARK",
    "market_relevance":           "operator-reviewed fixture row",
    "inclusion_reason":           "fixture include row",
    "operator_notes":             "fixture only - no real ticker resolution",
    "include_in_daily_section_c": "yes",
}
_EXCLUDED_ROW: dict[str, str] = {
    "candidate_id":               _EXCLUDED_CANDIDATE_ID,
    "headline":                   "Excluded Daily candidate fixture",
    "event_date":                 "2026-05-15",
    "mechanism_family":           "supply_shock",
    "primary_ticker":             "FIXTURE_PRIMARY_X",
    "benchmark_ticker":           "FIXTURE_BENCHMARK_X",
    "market_relevance":           "fixture exclusion row",
    "inclusion_reason":           "operator chose to exclude this row",
    "operator_notes":             "fixture only - emitter performs a silent skip",
    "include_in_daily_section_c": "no",
}


_HOLD_REASON_NO_ARTIFACT: str = (
    "no analyzed_event_artifact_<candidate_id>.json on the temp "
    "artifact directory; the gate holds the row for operator review"
)


# ---------------------------------------------------------------------------
# Patchable seam — lazy emitter import
# ---------------------------------------------------------------------------


def _run_emitter(
    *, input_path: str, output_dir: str,
) -> dict[str, Any]:
    """Run the operator-reviewed Daily artifact emitter against the
    smoke's temp CSV and write artifacts into the smoke's temp
    artifact directory.

    Lazy-imports the emitter so the smoke's top-level import
    surface stays narrow.  Tests patch this seam to drive failure
    paths without depending on the on-disk emitter.
    """
    from scripts.daily_analyzed_event_artifact_emitter import run_emitter
    return run_emitter(
        input_path=input_path,
        output_dir=output_dir,
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
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


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
# Card source — derive Daily cards from an artifact directory
# ---------------------------------------------------------------------------


def _cards_from_artifact_dir(
    artifact_dir: Path,
) -> list[dict[str, Any]]:
    """Build Daily mover cards from every
    ``analyzed_event_artifact_<cid>.json`` present under
    ``artifact_dir``.

    Each card carries the ``candidate_id`` parsed from the
    filename plus the ``headline`` from the artifact body (empty
    string when the body is unreadable).  The card source is
    intentionally minimal: it never invents ``candidate_id``,
    never resolves tickers, and never enriches fields the
    operator did not review.  ``artifact_dir`` is read-only.
    """
    cards: list[dict[str, Any]] = []
    if not artifact_dir.is_dir():
        return cards
    prefix = "analyzed_event_artifact_"
    for p in sorted(artifact_dir.glob(f"{prefix}*.json")):
        stem = p.stem
        if not stem.startswith(prefix):
            continue
        cid = stem[len(prefix):]
        if not cid:
            continue
        headline = ""
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
        if isinstance(doc, dict):
            value = doc.get("headline")
            if isinstance(value, str):
                headline = value
        cards.append({
            "candidate_id": cid,
            "headline":     headline,
        })
    return cards


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_daily_reviewed_artifact_end_to_end_smoke() -> dict[str, Any]:
    """Wire the four steps of the reviewed Daily path together and
    return the 10-key envelope.  See module docstring for the full
    output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    artifacts_before  = _hash_dir(_REAL_ARTIFACTS_DIR)
    news_inbox_before = _hash_file(_REAL_NEWS_INBOX)

    worksheet_rows:        int = 0
    artifacts_written:     int = 0
    cards_loaded:          int = 0
    admitted_items: list[dict[str, Any]] = []
    held_items:     list[dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory(
            prefix="daily_reviewed_artifact_end_to_end_smoke_",
        ) as tmp:
            tmp_root = Path(tmp)
            artifact_dir = tmp_root / "artifacts"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            csv_path = tmp_root / "reviewed_daily_worksheet.csv"

            rows = [_INCLUDED_ROW, _EXCLUDED_ROW]
            worksheet_rows = len(rows)
            _write_worksheet_csv(csv_path, rows)

            try:
                emit_envelope = _run_emitter(
                    input_path=str(csv_path),
                    output_dir=str(artifact_dir),
                )
            except Exception as exc:  # noqa: BLE001 — operator-visible
                errors.append(
                    f"emitter raised "
                    f"{type(exc).__name__}: {exc}"
                )
                emit_envelope = {}

            if isinstance(emit_envelope, dict):
                for e in emit_envelope.get("errors") or []:
                    if isinstance(e, str) and e:
                        errors.append(f"emitter: {e}")
                for w in emit_envelope.get("warnings") or []:
                    if isinstance(w, str) and w:
                        warnings.append(f"emitter: {w}")
                emitted = emit_envelope.get("emitted_count")
                if isinstance(emitted, int) and not isinstance(emitted, bool):
                    artifacts_written = emitted

            cards = _cards_from_artifact_dir(artifact_dir)
            cards_loaded = len(cards)

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
                doc = _read_artifact_doc(artifact_dir, cid)
                admitted_items.append({
                    "candidate_id":     cid,
                    "headline":         _str_field(doc, "headline"),
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
    except OSError as exc:
        errors.append(f"temp dir setup failed: {exc}")

    artifacts_after  = _hash_dir(_REAL_ARTIFACTS_DIR)
    news_inbox_after = _hash_file(_REAL_NEWS_INBOX)
    real_files_unchanged = (
        artifacts_before == artifacts_after
        and news_inbox_before == news_inbox_after
    )
    if not real_files_unchanged:
        errors.append(
            "real artifacts/ or news_inbox.json bytes changed during "
            "the smoke run - investigate before relying on the verdict"
        )

    admitted_count        = len(admitted_items)
    held_for_review_count = len(held_items)

    # Expected outcome — at least one admitted card AND the
    # included candidate_id appears in admitted_candidates so
    # the artifact filename ↔ candidate_id link is intact.
    if admitted_count < 1 and not errors:
        errors.append(
            "end-to-end smoke did not admit any artifact-backed "
            f"Daily candidate; expected admitted_count >= 1 with "
            f"candidate_id={_INCLUDED_CANDIDATE_ID!r}"
        )
    else:
        admitted_ids_seen = {
            i.get("candidate_id") for i in admitted_items
        }
        if (
            _INCLUDED_CANDIDATE_ID not in admitted_ids_seen
            and not errors
        ):
            errors.append(
                f"included candidate_id "
                f"{_INCLUDED_CANDIDATE_ID!r} did not appear in "
                f"admitted_candidates"
            )

    ok = not errors

    return {
        "ok":                    ok,
        "worksheet_rows":        worksheet_rows,
        "artifacts_written":     artifacts_written,
        "cards_loaded":          cards_loaded,
        "admitted_count":        admitted_count,
        "held_for_review_count": held_for_review_count,
        "admitted_candidates":   admitted_items,
        "real_files_unchanged":  real_files_unchanged,
        "warnings":              warnings,
        "errors":                errors,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_worksheet_csv(
    path: Path, rows: list[dict[str, str]],
) -> None:
    """Write the operator-reviewed Daily worksheet CSV into the
    smoke's temp directory.  The 10-column header mirrors the
    emitter's expected input schema; rows that omit a field get a
    blank string in that column rather than a missing column.
    """
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(_WORKSHEET_FIELDS),
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {k: r.get(k, "") for k in _WORKSHEET_FIELDS}
            )


def _read_artifact_doc(
    artifact_dir: Path, candidate_id: str,
) -> dict[str, Any]:
    """Re-read the temp artifact for an admitted candidate so the
    envelope's ``admitted_candidates`` block carries the
    artifact-backed fields.  The gate already validated the
    artifact; this re-read only enriches admitted items and never
    overrides the gate's verdict.
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
        f"[headline={item.get('headline', '')!r}, "
        f"mechanism_family={item.get('mechanism_family', '')}, "
        f"primary_ticker={item.get('primary_ticker', '')}, "
        f"benchmark_ticker={item.get('benchmark_ticker', '')}]"
    )


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Daily reviewed-artifact end-to-end smoke", ""]
    lines.append(f"OK:                    {report['ok']}")
    lines.append(f"Worksheet rows:        {report['worksheet_rows']}")
    lines.append(f"Artifacts written:     {report['artifacts_written']}")
    lines.append(f"Cards loaded:          {report['cards_loaded']}")
    lines.append(f"Admitted:              {report['admitted_count']}")
    for item in report["admitted_candidates"]:
        if isinstance(item, dict):
            lines.append(f"  - {_fmt_admitted(item)}")
    lines.append(
        f"Held for review:       {report['held_for_review_count']}"
    )
    lines.append(
        f"Real files unchanged:  {report['real_files_unchanged']}"
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
            "Read-only Daily reviewed-artifact end-to-end fixture "
            "smoke.  Writes a temp reviewed-Daily worksheet CSV, "
            "runs the production emitter against it into a temp "
            "artifact directory, builds Daily cards from the "
            "resulting artifacts, and feeds them through the same "
            "Daily Section C gate helper /movers/today calls.  "
            "Real artifacts/ and real news_inbox.json are hashed "
            "read-only before and after the run; any drift is "
            "surfaced as an error.  Never opens a DB, provider, "
            "LLM, or FastAPI surface.  No candidate_id is auto-"
            "generated; the included CSV row's daily-demo-001 "
            "flows to the artifact filename and the admitted card "
            "unchanged."
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


def _write_output(
    *, envelope: dict[str, Any], output_path: str,
) -> str | None:
    p = Path(output_path)
    if p.exists():
        return (
            f"--output path already exists; refusing to overwrite: "
            f"{output_path}"
        )
    try:
        p.write_text(_render_json(envelope), encoding="utf-8")
    except OSError as exc:
        return f"failed to write --output {output_path}: {exc}"
    return None


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = run_daily_reviewed_artifact_end_to_end_smoke()

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
    "run_daily_reviewed_artifact_end_to_end_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

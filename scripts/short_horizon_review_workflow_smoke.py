#!/usr/bin/env python3
"""Short-horizon reviewed workflow integration smoke.

Runs the full operator-reviewed short-horizon chain end-to-end::

    short_horizon_review_validator
        →  short_horizon_review_apply_smoke   (temp DB only)
            →  short_horizon_review_validate_smoke   (temp DB only)

so an operator can confirm the workflow mechanics carry a worksheet
from validator gate through staged candidates to short-horizon
evidence without ever touching the live archive or any paid /
provider / LLM / FastAPI surface.

Two modes
---------

* **Fixture mode** (default — no ``--worksheet``).  Builds a small,
  deterministic worksheet (one yes / one no / one pending row) and a
  scratch SQLite "events" DB in ``tempfile.gettempdir()``, then runs
  the chain against those.  In fixture mode the validate stage's
  ``_run_short_horizon_validation_on_temp_db`` seam is patched with a
  synthetic payload so the workflow exercise does NOT require the
  archive to carry short-horizon evidence — the fixture only
  demonstrates workflow mechanics, never market evidence.

* **Real worksheet mode** (``--worksheet PATH``).  Uses the supplied
  worksheet against the live events DB (``db.DB_FILE`` by default, or
  ``--db-path``).  Every underlying tool is read-only against the
  live DB by construction; apply staging lands in a temp copy.

Both modes are read-only against the live DB.  The smoke never opens
the live DB for writes; ``live_db_unchanged`` is propagated from the
apply smoke whose hash-before / hash-after guard is the source of
truth for archive byte identity.

Out of scope (deliberately)
---------------------------

* No live DB writes.  Apply staging is a temp copy.
* No call to ``yfinance``, ``market_data``, ``price_cache.fetch_*``,
  any paid provider, or an LLM.  The validator and apply smoke don't
  use any of these; the validate smoke's un-patched seam delegates
  to the read-only archive validation runner that reads existing
  ``price_cache`` rows only.
* No FastAPI surface — never imports ``api`` or ``routes.*``.

Output contract::

    {
      "ok":                       bool,
      "worksheet_path":           str | None,
      "validator_ok":             bool,
      "apply_ok":                 bool,
      "validate_ok":              bool,
      "accepted_count":           int,
      "staged_count":             int,
      "events_evaluated":         int,
      "records_count":            int,
      "significant_count":        int,
      "live_db_unchanged":        bool,
      "errors":                   [str, ...],
      "warnings":                 [str, ...],
      "recommended_next_action":  str,
    }

* ``accepted_count`` is propagated from the apply smoke (count of
  ``yes``-gated worksheet rows the apply stage attempted to stage).
  The validator's ``include_count`` should match it; a divergence
  lands in ``warnings`` for operator visibility.
* ``staged_count`` is the apply smoke's count of rows that actually
  landed in the temp DB's ``curated_candidates`` table.  It can be
  lower than ``accepted_count`` when a yes-row missed a required
  field or collided with the UNIQUE constraint on a repeat run.
* ``events_evaluated`` / ``records_count`` / ``significant_count``
  are propagated from the validate smoke and reflect the 1d/5d
  evidence for the accepted event_ids only.
* ``live_db_unchanged`` is True iff the apply smoke confirmed
  byte-identity of the live DB before / after.  The validate smoke
  is read-only by construction and does not vote.
* ``recommended_next_action`` is operator-facing prose; the first
  segment labels the run as fixture or real-worksheet so a consumer
  can tell modes apart from the envelope alone.

Conservative wording
--------------------

The fixture mode proves *workflow mechanics*, NEVER market evidence.
Banned tokens in any text the smoke emits: ``proof``, ``proven``,
``validated``, ``automatically``, ``alpha generated``,
``correct ticker``.  The fixture envelope is explicit that it
"demonstrates workflow mechanics" and "does not establish market
evidence."

Usage::

    python scripts/short_horizon_review_workflow_smoke.py --json
    python scripts/short_horizon_review_workflow_smoke.py \\
        --worksheet artifacts/short_horizon_review_top10.csv --json
    python scripts/short_horizon_review_workflow_smoke.py --json \\
        --output artifacts/short_horizon_review_workflow_smoke.json
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterator, Sequence
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import short_horizon_review_apply_smoke as _apply  # noqa: E402
from scripts import short_horizon_review_fixture as _fixture  # noqa: E402
from scripts import short_horizon_review_validate_smoke as _validate  # noqa: E402
from scripts import short_horizon_review_validator as _validator  # noqa: E402


_MODE_FIXTURE: str = "fixture"
_MODE_REAL:    str = "real_worksheet"


# Canonical short-horizon review worksheet columns, in the order
# emitted by ``scripts.short_horizon_review_worksheet``.  The
# validator requires the gate + four ``proposed_*`` columns + the
# ``exclude_reason`` column; the apply smoke additionally requires
# ``event_id``.  The fixture writes the full canonical header so the
# validator's column-shape check passes on the first try.
_FIXTURE_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# Deterministic fixture event ids come from the canonical fixture
# generator in ``scripts.short_horizon_review_fixture``.  Computed at
# import time so the workflow smoke and the canonical fixture stay in
# lock-step without duplicating the row payload.
def _canonical_fixture_event_ids() -> tuple[int, ...]:
    return tuple(int(r["event_id"]) for r in _fixture.build_fixture_rows())


def _canonical_accepted_event_ids() -> tuple[int, ...]:
    """Subset of canonical fixture event_ids whose gate is ``yes``."""
    return tuple(
        int(r["event_id"])
        for r in _fixture.build_fixture_rows()
        if str(
            r.get("include_in_short_horizon_validation") or ""
        ).strip().lower() == "yes"
    )


_EVENTS_DDL: str = """
CREATE TABLE events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    headline         TEXT,
    event_date       TEXT,
    market_tickers   TEXT,
    low_signal       INTEGER DEFAULT 0,
    mechanism_family TEXT DEFAULT 'none'
)
""".strip()


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_short_horizon_review_workflow_smoke(
    *,
    worksheet_path: str | None = None,
    db_path:        str | None = None,
    output_path:    str | None = None,
) -> dict[str, Any]:
    """Run the reviewed short-horizon workflow integration smoke.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    mode = _MODE_REAL if worksheet_path else _MODE_FIXTURE
    fixture_cleanup: list[str] = []
    effective_worksheet: str | None = worksheet_path
    effective_db_path:   str | None = db_path

    if mode == _MODE_FIXTURE:
        warnings.append(
            "running in fixture mode: fixture worksheet + scratch DB "
            "in tempdir; demonstrates workflow mechanics, does not "
            "establish market evidence"
        )
        try:
            (
                effective_worksheet, effective_db_path, fixture_cleanup,
            ) = _build_fixture()
        except OSError as exc:
            errors.append(f"failed to build fixture: {exc}")
            return _finalize(
                envelope=_envelope(
                    worksheet_path=worksheet_path,
                    mode=mode,
                    errors=errors, warnings=warnings,
                ),
                output_path=output_path,
                cleanup=fixture_cleanup,
            )
    else:
        warnings.append(
            "running in real worksheet mode: operator-supplied "
            "worksheet against the live events DB; no live DB writes"
        )
        if not effective_db_path:
            effective_db_path = _resolve_default_db_path()

    try:
        envelope = _run_chain(
            mode=mode,
            worksheet_path=effective_worksheet,
            display_worksheet=worksheet_path or effective_worksheet,
            db_path=effective_db_path,
            errors=errors,
            warnings=warnings,
        )
    finally:
        pass  # cleanup runs at the end so all reports are valid first

    envelope = _finalize(
        envelope=envelope,
        output_path=output_path,
        cleanup=fixture_cleanup,
    )
    return envelope


def _run_chain(
    *,
    mode: str,
    worksheet_path: str | None,
    display_worksheet: str | None,
    db_path: str | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Drive validator → apply → validate; collate into the envelope."""

    # Step 1: validator (CSV-only, no DB).
    validator_report = _validator.validate_review_worksheet(worksheet_path)
    validator_ok = bool(validator_report.get("ok"))
    for e in validator_report.get("errors") or []:
        errors.append(f"validator: {e}")
    for w in validator_report.get("warnings") or []:
        warnings.append(f"validator: {w}")

    # Step 2: apply smoke (temp DB only).
    if mode == _MODE_FIXTURE:
        apply_seam = _patch_apply_for_fixture()
    else:
        apply_seam = contextlib.nullcontext()
    with apply_seam:
        apply_report = _apply.smoke_short_horizon_review_apply(
            worksheet_path=worksheet_path,
            db_path=db_path,
        )
    apply_ok = bool(apply_report.get("ok"))
    accepted_count   = int(apply_report.get("accepted_count")   or 0)
    staged_count     = int(apply_report.get("staged_count")     or 0)
    live_db_unchanged = bool(apply_report.get("live_db_unchanged"))
    for e in apply_report.get("errors") or []:
        errors.append(f"apply: {e}")
    for w in apply_report.get("warnings") or []:
        warnings.append(f"apply: {w}")

    # Cross-check validator and apply on accepted count.  A divergence
    # is a worksheet-shape signal worth surfacing; never an error.
    validator_include = int(validator_report.get("include_count") or 0)
    if validator_include != accepted_count:
        warnings.append(
            f"validator include_count={validator_include} differs from "
            f"apply accepted_count={accepted_count}; some yes rows may "
            f"have been dropped at apply for missing required fields"
        )

    # Step 3: validate smoke (temp DB only via its patchable seam).
    if mode == _MODE_FIXTURE:
        validate_seam = _patch_validate_for_fixture()
    else:
        validate_seam = contextlib.nullcontext()
    with validate_seam:
        validate_report = _validate.run_short_horizon_review_validate(
            worksheet_path=worksheet_path,
            db_path=db_path,
            output_path=None,
            limit=int(_validate._DEFAULT_LIMIT),
        )
    validate_ok = bool(validate_report.get("ok"))
    events_evaluated  = int(validate_report.get("events_evaluated")  or 0)
    records_count     = int(validate_report.get("records_count")     or 0)
    significant_count = int(validate_report.get("significant_count") or 0)
    for e in validate_report.get("errors") or []:
        errors.append(f"validate: {e}")
    for w in validate_report.get("warnings") or []:
        warnings.append(f"validate: {w}")

    recommended_next_action = _recommended_next_action(
        mode=mode,
        validator_ok=validator_ok,
        apply_ok=apply_ok,
        validate_ok=validate_ok,
        accepted_count=accepted_count,
        staged_count=staged_count,
        events_evaluated=events_evaluated,
        records_count=records_count,
        significant_count=significant_count,
        has_errors=bool(errors),
    )

    return _envelope(
        worksheet_path=display_worksheet,
        mode=mode,
        validator_ok=validator_ok,
        apply_ok=apply_ok,
        validate_ok=validate_ok,
        accepted_count=accepted_count,
        staged_count=staged_count,
        events_evaluated=events_evaluated,
        records_count=records_count,
        significant_count=significant_count,
        live_db_unchanged=live_db_unchanged,
        errors=errors,
        warnings=warnings,
        recommended_next_action=recommended_next_action,
    )


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_fixture() -> tuple[str, str, list[str]]:
    """Build a deterministic worksheet + scratch events DB pair in
    ``tempfile.gettempdir()``.  Returns ``(worksheet_path, db_path,
    cleanup_paths)``.  The cleanup list is the caller's responsibility
    to ``os.unlink`` at the end of the run.
    """
    cleanup: list[str] = []

    db_path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_workflow_fixture_db_{uuid.uuid4().hex}.db",
    )
    rows = _fixture.build_fixture_rows()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_EVENTS_DDL)
        for r in rows:
            ev_id = int(r["event_id"])
            conn.execute(
                "INSERT INTO events (id, headline, event_date) "
                "VALUES (?, ?, ?)",
                (
                    ev_id,
                    str(r.get("headline") or f"fixture headline {ev_id}"),
                    str(r.get("event_date") or "2026-04-15"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    cleanup.append(db_path)

    worksheet_path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_workflow_fixture_ws_{uuid.uuid4().hex}.csv",
    )
    with open(worksheet_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(_FIXTURE_COLUMNS)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in _FIXTURE_COLUMNS])
    cleanup.append(worksheet_path)

    return worksheet_path, db_path, cleanup


@contextlib.contextmanager
def _patch_apply_for_fixture() -> Iterator[None]:
    """Apply smoke is already temp-DB-only; no seam to patch for the
    fixture path.  Kept as a contextmanager so the call-site flow
    matches the validate-seam patcher and future seams can attach
    cleanly without restructuring the chain.
    """
    yield


@contextlib.contextmanager
def _patch_validate_for_fixture() -> Iterator[None]:
    """Patch the validate smoke's ``_run_short_horizon_validation_on_
    temp_db`` seam with a deterministic synthetic payload during
    fixture-mode runs.  The synthetic payload covers every ``yes``
    event_id from the canonical fixture at horizons 1 and 5 so the
    validate stage surfaces records for each accepted row.  It does
    NOT carry any market evidence and the envelope is explicit about
    that.
    """
    rows_by_event_id = {
        int(r["event_id"]): r for r in _fixture.build_fixture_rows()
    }
    accepted_ids = _canonical_accepted_event_ids()
    records: list[dict[str, Any]] = []
    for ev_id in accepted_ids:
        row = rows_by_event_id.get(ev_id, {})
        ticker = str(row.get("proposed_primary_ticker") or "")
        mechanism = str(row.get("proposed_mechanism_family") or "")
        headline = str(row.get("headline") or f"fixture headline {ev_id}")
        for horizon, ar, sar, ci_low, ci_high, p_value, fdr_q in (
            (1, 0.01, 0.5, -0.02, 0.04, 0.30, 0.40),
            (5, 0.02, 1.0, -0.01, 0.05, 0.15, 0.25),
        ):
            records.append({
                "event_id":         ev_id,
                "headline":         headline,
                "ticker":           ticker,
                "horizon":          horizon,
                "abnormal_return":  ar,
                "sar":              sar,
                "ci_low":           ci_low,
                "ci_high":          ci_high,
                "p_value":          p_value,
                "fdr_q":            fdr_q,
                "interpretation":   "not_significant",
                "mechanism_family": mechanism,
                "statistically_significant": False,
            })
    payload = {"ok": True, "records": records, "errors": []}
    with patch.object(
        _validate, "_run_short_horizon_validation_on_temp_db",
        return_value=payload,
    ):
        yield


# ---------------------------------------------------------------------------
# Operator prose
# ---------------------------------------------------------------------------


def _recommended_next_action(
    *,
    mode: str,
    validator_ok: bool,
    apply_ok: bool,
    validate_ok: bool,
    accepted_count: int,
    staged_count: int,
    events_evaluated: int,
    records_count: int,
    significant_count: int,
    has_errors: bool,
) -> str:
    """Operator-facing one-liner describing what to do next.  The
    first segment labels the mode so a consumer can read mode off the
    envelope without a separate field.  Conservative wording only —
    the fixture run demonstrates mechanics, never market evidence.
    """
    if mode == _MODE_FIXTURE:
        prefix = (
            "fixture-mode run — demonstrates workflow mechanics only; "
            "no market evidence carried"
        )
    else:
        prefix = "real-worksheet run"

    if has_errors:
        return (
            f"{prefix}; chain reported errors — inspect 'errors' before "
            f"acting on any downstream counts"
        )

    if accepted_count == 0:
        return (
            f"{prefix}; no operator-accepted rows on the worksheet — "
            f"fill yes/no gates and re-run before reading evidence"
        )

    if staged_count < accepted_count:
        return (
            f"{prefix}; {staged_count}/{accepted_count} accepted rows "
            f"staged — check apply errors for the dropped rows"
        )

    if events_evaluated == 0:
        return (
            f"{prefix}; {staged_count} candidate(s) staged but no "
            f"short-horizon records surfaced for the accepted event "
            f"ids — confirm price_cache coverage on the temp DB"
        )

    return (
        f"{prefix}; chain clean — {staged_count} candidate(s) staged, "
        f"{records_count} short-horizon record(s) surfaced across "
        f"{events_evaluated} event(s), {significant_count} flagged "
        f"significant; surfaced records are candidate evidence only"
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope(
    *,
    worksheet_path: str | None,
    mode: str,
    validator_ok:        bool = False,
    apply_ok:            bool = False,
    validate_ok:         bool = False,
    accepted_count:      int  = 0,
    staged_count:        int  = 0,
    events_evaluated:    int  = 0,
    records_count:       int  = 0,
    significant_count:   int  = 0,
    live_db_unchanged:   bool = True,
    errors:   list[str],
    warnings: list[str],
    recommended_next_action: str | None = None,
) -> dict[str, Any]:
    if recommended_next_action is None:
        recommended_next_action = _recommended_next_action(
            mode=mode,
            validator_ok=validator_ok,
            apply_ok=apply_ok,
            validate_ok=validate_ok,
            accepted_count=accepted_count,
            staged_count=staged_count,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            has_errors=bool(errors),
        )
    return {
        "ok":                       not errors,
        "worksheet_path":           worksheet_path,
        "validator_ok":             validator_ok,
        "apply_ok":                 apply_ok,
        "validate_ok":              validate_ok,
        "accepted_count":           accepted_count,
        "staged_count":             staged_count,
        "events_evaluated":         events_evaluated,
        "records_count":            records_count,
        "significant_count":        significant_count,
        "live_db_unchanged":        live_db_unchanged,
        "errors":                   errors,
        "warnings":                 warnings,
        "recommended_next_action":  recommended_next_action,
    }


def _finalize(
    *,
    envelope:    dict[str, Any],
    output_path: str | None,
    cleanup:     list[str],
) -> dict[str, Any]:
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    envelope, fh, indent=2, sort_keys=True, default=str,
                )
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    for p in cleanup:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            # Best-effort cleanup; never let unlink failure flip ok.
            pass

    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Short-horizon reviewed workflow integration smoke", "",
    ]
    lines.append(f"OK:                       {report['ok']}")
    lines.append(f"Worksheet path:           {report['worksheet_path']}")
    lines.append(f"Validator OK:             {report['validator_ok']}")
    lines.append(f"Apply OK:                 {report['apply_ok']}")
    lines.append(f"Validate OK:              {report['validate_ok']}")
    lines.append(f"Accepted count:           {report['accepted_count']}")
    lines.append(f"Staged count:             {report['staged_count']}")
    lines.append(f"Events evaluated:         {report['events_evaluated']}")
    lines.append(f"Records count:            {report['records_count']}")
    lines.append(f"Significant count:        {report['significant_count']}")
    lines.append(f"Live DB unchanged:        {report['live_db_unchanged']}")
    lines.append("")
    lines.append(
        f"Recommended next action:  {report['recommended_next_action']}"
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
            "Short-horizon reviewed workflow integration smoke.  Runs "
            "the validator -> apply -> validate chain against a "
            "fixture worksheet by default, or against a real operator "
            "worksheet via --worksheet.  No live DB writes; no "
            "provider / yfinance / LLM / FastAPI imports.  Conservative "
            "wording: fixture mode demonstrates workflow mechanics, "
            "never market evidence."
        ),
    )
    parser.add_argument(
        "--worksheet", dest="worksheet_path", default=None,
        help=(
            "Optional path to a reviewed short-horizon worksheet CSV.  "
            "When omitted, the smoke runs against a deterministic "
            "fixture worksheet built in tempdir."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB (used only when "
            "--worksheet is supplied).  Defaults to ``db.DB_FILE``.  "
            "Read-only by construction; staging lands in a temp copy."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the smoke has no filesystem side effect outside "
            "the fixture scratch files (auto-cleaned)."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_default_db_path() -> str | None:
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    db_path = args.db_path
    if args.worksheet_path and not db_path:
        db_path = _resolve_default_db_path()

    report = run_short_horizon_review_workflow_smoke(
        worksheet_path=args.worksheet_path,
        db_path=db_path,
        output_path=args.output_path,
    )

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_short_horizon_review_workflow_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""K13 — Phase-K funnel -> curated_observation bridge.

The missing wiring K12 identified.  A frozen Phase-K *funnel* row cannot feed
the curated-intake path: the funnel uses ``candidates:`` / ``candidate_id`` /
``predicted_direction: positive|negative`` and carries no
``mechanism_description`` / ``prediction_rationale``, while
``curated_event_intake_apply`` requires the ``events:`` schema
(``event_id`` / ``predicted_direction: up|down|flat`` / those two prose
fields).  Separately, ``curated_observation_promote`` requires a
``curated_candidates`` row carrying ``primary_ticker`` per event, and no
committed path creates one from a curated_intake event.

This bridge closes both gaps:

  1. :func:`transform_row` maps a funnel include row to a curated-intake
     event dict (direction positive->up / negative->down, synthesizing
     ``mechanism_description`` + ``prediction_rationale`` from the funnel's
     headline / subtype / falsifier / notes).  Malformed rows are refused.
  2. :func:`apply_bridge` (guarded) runs ``apply_curated_intake`` over the
     transformed events, then inserts the matching ``curated_candidates``
     rows the promote gate needs.

It performs NO returns, NO event-study validation, NO promotion (that is the
existing ``curated_observation_promote`` step), NO provider/LLM/paid call.
Dry-run is the default; writing requires the full ``--write --confirm
--backup-path`` triple.  Idempotent: re-running stages nothing new
(curated-intake is idempotent by ``source_url``; the candidate insert is
idempotent by ``(source_event_id, source)``).

Usage::

    python scripts/phase_k_funnel_to_curated.py --yaml examples/phase_k_tariff_sourcing_funnel.yaml          # dry-run
    python scripts/phase_k_funnel_to_curated.py --yaml FUNNEL.yaml --json                                    # dry-run JSON
    python scripts/phase_k_funnel_to_curated.py --yaml FUNNEL.yaml --db-path COPY.db \\
        --write --confirm --backup-path backups/pre-bridge.db                                                # guarded stage
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from typing import Any, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402
from mechanism_family import FAMILY_IDS  # noqa: E402


BRIDGE_SOURCE = "phase_k_bridge"
DEFAULT_SOURCE_TYPE = "official"
LABEL_PROVENANCE = "curated"

# Funnel sign vocabulary -> curated-intake ticker-direction vocabulary.
_DIRECTION_MAP = {
    "positive": "up", "up": "up",
    "negative": "down", "down": "down",
    "flat": "flat", "neutral": "flat",
}


# ---------------------------------------------------------------------------
# Pure transform
# ---------------------------------------------------------------------------


def _s(row: dict[str, Any], key: str) -> Any:
    v = row.get(key)
    if isinstance(v, str):
        return v.strip()
    return v


def transform_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Transform one funnel row into a curated-intake event dict.

    Returns ``(event_dict, [])`` on success or ``(None, errors)`` when the row
    is malformed (missing source_url / primary_ticker / event_date, invalid
    mechanism_family, or an unmappable predicted_direction).
    """
    errs: list[str] = []
    cid = _s(row, "candidate_id")
    src = _s(row, "source_url")
    prim = _s(row, "primary_ticker")
    ed = _s(row, "event_date")
    fam = _s(row, "mechanism_family")
    pdir = (_s(row, "predicted_direction") or "")
    pdir = pdir.lower() if isinstance(pdir, str) else pdir

    if not src:
        errs.append("missing source_url")
    if not prim:
        errs.append("missing primary_ticker")
    if not ed:
        errs.append("missing event_date")
    if not cid:
        errs.append("missing candidate_id (needed for event_id)")
    if fam not in FAMILY_IDS:
        errs.append(f"invalid mechanism_family: {fam!r}")
    mapped = _DIRECTION_MAP.get(pdir) if isinstance(pdir, str) else None
    if mapped is None:
        errs.append(f"unmappable predicted_direction: {pdir!r}")
    if errs:
        return None, errs

    bench = _s(row, "benchmark_ticker")
    subtype = _s(row, "mechanism_subtype") or ""
    notes = _s(row, "operator_notes") or ""
    falsifier = _s(row, "what_would_falsify") or ""
    headline = _s(row, "headline") or ""

    mech_desc = (
        f"{headline} [mechanism_family={fam}; subtype={subtype}]."
        + (f" {notes}" if notes else "")
    ).strip()
    rationale = (
        f"A priori direction '{mapped}' for {prim} vs {bench}, read off the "
        f"source. Falsifier: {falsifier}".strip()
    )
    if notes:
        rationale = f"{rationale} {notes}"

    event = {
        "event_id": cid,
        "event_date": ed,
        "headline": headline,
        "source_url": src,
        "source_type": DEFAULT_SOURCE_TYPE,
        "source_publisher": _s(row, "source_publisher"),
        "source_published_at": f"{ed}T00:00:00",
        "primary_ticker": prim,
        "benchmark_ticker": bench,
        "mechanism_family": fam,
        "mechanism_description": mech_desc,
        "predicted_direction": mapped,
        "prediction_rationale": rationale,
        "mechanism_label_provenance": LABEL_PROVENANCE,
        # carried for the curated_candidates insert (not part of intake schema):
        "_subtype": subtype,
    }
    return event, []


# ---------------------------------------------------------------------------
# Load + plan (pure read)
# ---------------------------------------------------------------------------


def _load_rows(yaml_path: str | None, rows: list[dict] | None) -> list[dict]:
    if rows is not None:
        return list(rows)
    if not yaml_path:
        return []
    import yaml
    with open(yaml_path, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return list(doc.get("candidates") or [])


def plan_bridge(
    *, yaml_path: str | None = None, rows: list[dict] | None = None,
) -> dict[str, Any]:
    """Classify a funnel's include rows into to_stage / skipped / rejected.  Read-only."""
    all_rows = _load_rows(yaml_path, rows)
    to_stage: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for r in all_rows:
        if not isinstance(r, dict):
            continue
        if r.get("include_in_validation") is not True:
            skipped.append({"candidate_id": r.get("candidate_id"),
                            "reason": "include_in_validation is not true"})
            continue
        ev, errs = transform_row(r)
        if errs:
            rejected.append({"candidate_id": r.get("candidate_id"), "errors": errs})
        else:
            to_stage.append(ev)
    return {
        "ok": not rejected,
        "to_stage": to_stage,
        "to_stage_count": len(to_stage),
        "skipped": skipped,
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# Guarded apply
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _event_id_by_source_url(target: str, source_url: str) -> int | None:
    """Resolve the events.id for a provenance source_url (post-intake)."""
    try:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT event_id FROM event_provenance WHERE source_url = ? "
            "ORDER BY event_id LIMIT 1", (source_url,),
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def _upsert_candidate(
    conn: sqlite3.Connection, *, event: dict[str, Any], event_id: int, source: str,
) -> bool:
    """Insert a curated_candidates row for ``event_id`` if absent. Idempotent
    by ``(source_event_id, source)``.  Returns True when a row was inserted."""
    exists = conn.execute(
        "SELECT 1 FROM curated_candidates WHERE source_event_id = ? AND source = ?",
        (event_id, source),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO curated_candidates ("
        "source_event_id, event_date, headline, source_url, primary_ticker, "
        "benchmark_ticker, mechanism_family, mechanism_description, "
        "predicted_direction, prediction_rationale, curator_notes, status, "
        "source, created_at, validation_errors) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id, event.get("event_date"), event.get("headline"),
            event.get("source_url"), event.get("primary_ticker"),
            event.get("benchmark_ticker"), event.get("mechanism_family"),
            event.get("mechanism_description"), event.get("predicted_direction"),
            event.get("prediction_rationale"), event.get("_subtype") or "",
            "draft", source, _now_iso(), "[]",
        ),
    )
    return True


def apply_bridge(
    *, yaml_path: str | None = None, rows: list[dict] | None = None,
    db_path: str | None = None, confirm: bool = False,
    backup_path: str | None = None, source: str = BRIDGE_SOURCE,
) -> dict[str, Any]:
    """Stage funnel includes as curated_intake events + curated_candidates rows.

    Dry-run unless ``confirm`` with a ``backup_path`` and a reject-free plan.
    Reuses the guarded ``curated_event_intake_apply`` for the events/provenance
    write, then inserts the matching ``curated_candidates`` rows.
    """
    plan = plan_bridge(yaml_path=yaml_path, rows=rows)
    envelope: dict[str, Any] = {
        **plan,
        "write_attempted": False,
        "staged": [],
        "backup_path": None,
        "refuse_reason": None,
        "error": None,
    }
    if not confirm:
        return envelope

    target = db_path if db_path is not None else db.get_db_path()
    if not backup_path:
        envelope["refuse_reason"] = "--backup-path is required for --write"
        return envelope
    if plan["rejected"]:
        envelope["refuse_reason"] = (
            "refusing to write: one or more include rows failed transform "
            "(fix the funnel and re-run; the bridge is idempotent)"
        )
        return envelope
    if not plan["to_stage"]:
        return envelope  # clean no-op

    # 1) Guarded curated-intake write (events + event_provenance), idempotent by source_url.
    from scripts.curated_event_intake_apply import apply_curated_intake
    intake = apply_curated_intake(
        events=plan["to_stage"], db_path=target, confirm=True,
        backup_path=backup_path,
    )
    envelope["backup_path"] = intake.get("backup_path")
    if intake.get("refuse_reason") or intake.get("error"):
        envelope["refuse_reason"] = intake.get("refuse_reason")
        envelope["error"] = intake.get("error")
        return envelope

    # 2) Create curated_candidates rows the promote gate needs.  Resolve each
    #    event_id by source_url (covers fresh inserts AND idempotent re-runs).
    staged: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(target, isolation_level=None, timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for ev in plan["to_stage"]:
                    eid = _event_id_by_source_url(target, ev["source_url"])
                    if eid is None:
                        continue
                    inserted = _upsert_candidate(
                        conn, event=ev, event_id=eid, source=source,
                    )
                    staged.append({
                        "candidate_id": ev["event_id"], "event_id": eid,
                        "source_url": ev["source_url"],
                        "candidate_inserted": inserted,
                    })
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        envelope["error"] = f"{type(exc).__name__}: {exc}"
        return envelope

    envelope["write_attempted"] = True
    envelope["staged"] = staged
    return envelope


# ---------------------------------------------------------------------------
# Rendering + CLI
# ---------------------------------------------------------------------------


def _public(report: dict[str, Any]) -> dict[str, Any]:
    out = dict(report)
    out["to_stage"] = [
        {k: v for k, v in e.items() if k != "_subtype"} for e in report.get("to_stage", [])
    ]
    return out


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(_public(report), indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    is_write = "write_attempted" in report
    lines = [
        "Phase-K funnel -> curated bridge — "
        + ("write" if report.get("write_attempted") else "dry-run"),
        "",
        f"ok:             {report.get('ok')}",
        f"to_stage_count: {report.get('to_stage_count')}",
        f"skipped:        {len(report.get('skipped') or [])}",
        f"rejected:       {len(report.get('rejected') or [])}",
    ]
    for e in report.get("to_stage") or []:
        lines.append(f"  + {e.get('event_id')}: {e.get('primary_ticker')} "
                     f"[{e.get('predicted_direction')}] {e.get('source_url')}")
    for r in report.get("rejected") or []:
        lines.append(f"  x {r.get('candidate_id')}: {r.get('errors')}")
    if is_write:
        lines += ["", "Write:",
                  f"  backup_path:     {report.get('backup_path')}",
                  f"  write_attempted: {report.get('write_attempted')}",
                  f"  staged:          {len(report.get('staged') or [])}"]
        if report.get("refuse_reason"):
            lines.append(f"  refuse_reason:   {report.get('refuse_reason')}")
        if report.get("error"):
            lines.append(f"  error:           {report.get('error')}")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bridge frozen Phase-K funnel rows into curated_intake "
                    "events + curated_candidates so they can be promoted to "
                    "curated_observation.  Dry-run by default.")
    p.add_argument("--yaml", dest="yaml_path", required=True,
                   help="Path to a Phase-K funnel YAML.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Target SQLite events.db (use a COPY). Defaults to db.DB_FILE.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    p.add_argument("--dry-run", action="store_true", help="Explicit dry-run (default).")
    p.add_argument("--write", action="store_true",
                   help="Persist. Requires --confirm and --backup-path.")
    p.add_argument("--confirm", action="store_true", help="Confirm a --write run.")
    p.add_argument("--backup-path", dest="backup_path", default=None,
                   help="Snapshot path before writing (required for --write).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    if args.dry_run or not (args.write or args.confirm):
        report = _public(plan_bridge(yaml_path=args.yaml_path))
    else:
        if not (args.write and args.confirm):
            print("Refusing: --write and --confirm must be supplied together.",
                  file=sys.stderr)
            return 2
        if not args.backup_path:
            print("Refusing: --write also requires --backup-path.", file=sys.stderr)
            return 2
        report = apply_bridge(yaml_path=args.yaml_path, db_path=args.db_path,
                              confirm=True, backup_path=args.backup_path)
    print(_render_json(report) if args.json else _render_text(report), file=output)
    if "write_attempted" in report and (report.get("refuse_reason") or report.get("error")):
        return 1
    return 0 if report.get("ok") else 1


__all__ = ("transform_row", "plan_bridge", "apply_bridge", "main", "BRIDGE_SOURCE")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""D1B — guarded writer for the curated-event intake.

Takes operator-curated YAML events (parsed by
:mod:`scripts.curated_event_loader` and field-validated by
:mod:`scripts.curated_event_validator`) and persists each accepted event
as ONE ``events`` row plus ONE matching ``event_provenance`` row.  This
is the write half of the D1A provenance schema: D1A added the table and
the read helpers; D1B adds the only path that fills it.

Two-phase, guarded-write contract
---------------------------------
* :func:`plan_curated_intake` is a pure read — it loads + validates, reads
  the existing ``event_provenance.source_url`` set, and classifies each
  event into *to-insert* / *skipped (already present)* / *rejected*.  It
  never writes (it does not even create the DB file when one is absent).
* :func:`apply_curated_intake` writes nothing unless ``confirm=True`` AND a
  ``backup_path`` is supplied AND every event is acceptable.  Before any
  mutation it snapshots the target DB to ``backup_path`` (refusing when
  ``backup_path`` resolves to the target itself).  All inserts run inside
  a single ``BEGIN IMMEDIATE`` transaction and roll back together on any
  error — one all-or-nothing transaction, by design.

Idempotency
-----------
``event_provenance.source_url`` is the all-time idempotency key.  An
event whose ``source_url`` already has a provenance row is skipped, and a
``source_url`` duplicated within a single batch inserts once.  A re-run of
the same YAML therefore inserts nothing.

What gets persisted (honest, minimal mapping)
---------------------------------------------
The ``events`` row carries ONLY the clean 1:1 columns:

  * ``headline``        ← curated ``headline``
  * ``event_date``      ← curated ``event_date`` (ISO ``YYYY-MM-DD``)
  * ``mechanism_family``← curated ``mechanism_family``
  * ``notes``           ← curated ``curator_notes`` (optional)
  * ``stage``           = ``"curated_intake"`` (inert non-analysis marker)
  * ``persistence``     = ``"unscored"``       (inert non-analysis marker)
  * ``timestamp``       = intake ``created_at``

Analysis-output columns (``market_tickers``, ``mechanism_summary``,
``proof_status``, …) are deliberately left at their schema defaults so no
aggregator or dashboard misreads curated intake as analysis.  In
particular ``predicted_direction`` and ``prediction_rationale`` are
validated by the reused validator but are NOT persisted (no directional
framing).  ``primary_ticker`` / ``benchmark_ticker`` /
``mechanism_description`` stay in the YAML — the row is recoverable by its
``source_url`` — and are wired by a later phase, not here.

The ``event_provenance`` row stores the source-side fields verbatim, with
conservative defaults for hand-authored YAML:

  * ``source_type``                 ← event or ``"curated"``
  * ``source_publisher``            ← event or NULL
  * ``source_url``                  ← event (required)
  * ``source_published_at``         ← event or NULL
  * ``mechanism_label_provenance``  ← event or ``"curated"`` (vocabulary:
        ``curated`` / ``model`` / ``keyword_fallback`` / ``unknown`` —
        enforced here, the value layer D1A deferred; stored verbatim and
        never upgraded, so an LLM-inferred label stays ``model``)
  * ``intake_path``                 = ``"curated_yaml"``
  * ``created_at``                  = intake ``created_at``

Source-anchoring (``derive_provenance_status``) is computed on read from
``source_url`` + ``source_published_at`` and is orthogonal to the
mechanism-label provenance.

Out of scope (deliberately)
---------------------------
* Never mutates or retroactively source-anchors legacy rows.
* No pre-registration manifest, no cohort / FDR statistics.
* No provider, ``yfinance``, ``market_check``, ``market_data``,
  ``price_cache``, LLM, or FastAPI surface — and no paid calls.

Usage::

    python scripts/curated_event_intake_apply.py --yaml examples/curated_events.example.yaml          # dry-run
    python scripts/curated_event_intake_apply.py --yaml worksheet.yaml --json                          # dry-run JSON
    python scripts/curated_event_intake_apply.py --yaml worksheet.yaml \\
        --write --confirm --backup-path backups/pre-intake.db                                          # guarded write
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import sqlite3
import sys
from typing import Any, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Intake constants — the value layer D1A deferred to the write path.
# ---------------------------------------------------------------------------

#: Inert non-analysis markers stamped onto the NOT NULL scaffolding columns
#: so a curated-intake row is never mistaken for an analysed event.  Both
#: are unknown to every ``stage`` / ``persistence`` reader (which branch on
#: equality), so they read as neutral and give a later phase a clean handle
#: to filter intake rows out of analysis denominators.
INTAKE_STAGE = "curated_intake"
INTAKE_PERSISTENCE = "unscored"
INTAKE_PATH = "curated_yaml"

DEFAULT_SOURCE_TYPE = "curated"
DEFAULT_MECHANISM_LABEL_PROVENANCE = "curated"

#: ``mechanism_label_provenance`` vocabulary (D1A left this unconstrained in
#: the schema; the write layer enforces it now that the values are real).
VALID_MECHANISM_LABEL_PROVENANCE: frozenset[str] = frozenset({
    "curated",          # a human read the label off the source
    "model",            # an LLM inferred it
    "keyword_fallback", # a keyword classifier produced it
    "unknown",          # legacy / backfill, provenance not recorded
})

#: Source types whose claim is only credible with a URL to the primary
#: document.  (A curated event already requires ``source_url`` at
#: validation; this guard restates the rule for these high-trust types.)
SOURCE_TYPES_REQUIRING_URL: frozenset[str] = frozenset({
    "official", "regulator", "exchange",
})


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(db_path: str | None) -> str:
    """Resolve the target events DB path (falls back to ``db.DB_FILE``)."""
    if db_path is not None:
        return db_path
    import db as _db
    return _db.get_db_path()


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _coerce_date_str(value: Any) -> Any:
    """Render a validated event_date as an ISO ``YYYY-MM-DD`` string.

    The validator accepts either an ISO string or a ``datetime.date``;
    SQLite stores the column as text, so normalise both to a string.
    """
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    return value


def _same_path(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` denote the same file on disk."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.abspath(a) == os.path.abspath(b)


def _str_field(event: dict[str, Any], key: str, default: str = "") -> str:
    value = event.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _opt_field(event: dict[str, Any], key: str) -> str | None:
    """Return a stripped non-blank string for ``key``, else ``None``."""
    value = event.get(key)
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value)
    return text or None


def _intake_guard_errors(event: dict[str, Any]) -> list[str]:
    """Intake-layer guard errors for one (already field-valid) event.

    These sit on top of the reused field validator: they enforce the
    source-provenance relationships and the ``mechanism_label_provenance``
    vocabulary the schema leaves open.  Returns an empty list when the
    event is acceptable for intake.
    """
    errors: list[str] = []
    source_url = _str_field(event, "source_url")
    source_type = _str_field(event, "source_type", DEFAULT_SOURCE_TYPE)
    published_at = _str_field(event, "source_published_at")
    mech_prov = _str_field(
        event, "mechanism_label_provenance", DEFAULT_MECHANISM_LABEL_PROVENANCE,
    )

    if not source_url:
        errors.append(
            "curated event requires a source_url (the all-time idempotency key)"
        )
    if source_type in SOURCE_TYPES_REQUIRING_URL and not source_url:
        errors.append(f"source_type {source_type!r} requires a source_url")
    if published_at and not source_url:
        errors.append(
            "a source-anchored event (source_published_at set) requires a "
            "source_url"
        )
    if mech_prov not in VALID_MECHANISM_LABEL_PROVENANCE:
        errors.append(
            "mechanism_label_provenance must be one of "
            f"{sorted(VALID_MECHANISM_LABEL_PROVENANCE)}; got {mech_prov!r}"
        )
    return errors


def _provenance_row_for_event(
    event: dict[str, Any], *, created_at: str,
) -> dict[str, Any]:
    """Build the ``event_provenance`` payload (verbatim source fields)."""
    return {
        "source_type":         _str_field(
            event, "source_type", DEFAULT_SOURCE_TYPE),
        "source_publisher":    _opt_field(event, "source_publisher"),
        "source_url":          _str_field(event, "source_url"),
        "source_published_at": _opt_field(event, "source_published_at"),
        "mechanism_label_provenance": _str_field(
            event, "mechanism_label_provenance",
            DEFAULT_MECHANISM_LABEL_PROVENANCE),
        "intake_path":         INTAKE_PATH,
        "created_at":          created_at,
    }


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    """A small JSON-safe preview of an event for the report."""
    return {
        "event_id":         event.get("event_id"),
        "source_url":       _str_field(event, "source_url"),
        "headline":         _str_field(event, "headline"),
        "mechanism_family": _str_field(event, "mechanism_family"),
    }


# ---------------------------------------------------------------------------
# Load + validate (reuses the D1A loader + validator)
# ---------------------------------------------------------------------------


def _load_and_validate(
    yaml_path: str | None, events: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(validation_report, load_errors)``.

    When ``events`` is supplied it is validated directly; otherwise the
    archive is loaded from ``yaml_path`` first.  Both paths run the same
    field validator so the contract is identical.
    """
    from scripts.curated_event_validator import validate_curated_events

    if events is None:
        from scripts.curated_event_loader import load_curated_events
        events, load_errors = load_curated_events(yaml_path)
    else:
        load_errors = []
    report = validate_curated_events(list(events))
    return report, list(load_errors)


def _existing_source_urls(target: str) -> set[str]:
    """Return every ``source_url`` already recorded in ``event_provenance``.

    Read-only.  Returns an empty set when the DB file does not exist yet
    (so the planner never creates the file) or the table is absent.
    """
    if not target or not os.path.exists(target):
        return set()
    try:
        conn = sqlite3.connect(target)
    except sqlite3.Error:
        return set()
    try:
        try:
            rows = conn.execute(
                "SELECT source_url FROM event_provenance "
                "WHERE source_url IS NOT NULL AND TRIM(source_url) != ''"
            ).fetchall()
        except sqlite3.Error:
            return set()
        return {r[0] for r in rows if r[0]}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dry-run planner — pure read
# ---------------------------------------------------------------------------


def plan_curated_intake(
    *,
    yaml_path: str | None = None,
    events: list[dict[str, Any]] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Classify curated events into insert / skip / reject.  Read-only.

    Returns a dict with ``ok`` (writable only when True), the
    ``validation_errors`` envelope, ``to_insert`` (small previews),
    ``skipped_existing``, ``rejected`` (validation + intake-guard
    failures), and a private ``_insert_events`` list of full event dicts
    the writer consumes.
    """
    report, load_errors = _load_and_validate(yaml_path, events)
    validated = report.get("validated_events") or []
    validation_errors = list(load_errors) + list(report.get("errors") or [])

    rejected: list[dict[str, Any]] = []
    # Field-validation failures (missing / malformed fields) block the batch.
    for ev_id_key, errs in (report.get("errors_by_event_id") or {}).items():
        rejected.append({"event_id": ev_id_key, "errors": list(errs)})

    target = _resolve_db_path(db_path)
    existing = _existing_source_urls(target)

    insert_events: list[dict[str, Any]] = []
    to_insert: list[dict[str, Any]] = []
    skipped_existing: list[dict[str, Any]] = []
    seen_in_batch: set[str] = set()

    for event in validated:
        guard_errs = _intake_guard_errors(event)
        if guard_errs:
            rejected.append({
                "event_id": event.get("event_id"),
                "errors":   guard_errs,
            })
            continue
        url = _str_field(event, "source_url")
        if url in existing:
            skipped_existing.append({
                "event_id":   event.get("event_id"),
                "source_url": url,
                "reason":     "source_url already present in event_provenance",
            })
            continue
        if url in seen_in_batch:
            skipped_existing.append({
                "event_id":   event.get("event_id"),
                "source_url": url,
                "reason":     "duplicate source_url within this batch",
            })
            continue
        seen_in_batch.add(url)
        insert_events.append(event)
        to_insert.append(_event_summary(event))

    ok = (not validation_errors) and (not rejected)

    return {
        "ok":                ok,
        "validation_errors": validation_errors,
        "validated_count":   len(validated),
        "to_insert":         to_insert,
        "to_insert_count":   len(to_insert),
        "skipped_existing":  skipped_existing,
        "rejected":          rejected,
        "_insert_events":    insert_events,
    }


# ---------------------------------------------------------------------------
# Insert helpers — patchable seams (the rollback test patches the second).
# ---------------------------------------------------------------------------


def _insert_event_row(
    conn: sqlite3.Connection, event: dict[str, Any], *, created_at: str,
) -> int:
    """Insert one curated event into ``events``; return its new id.

    Only the honest 1:1 columns are written; every analysis-output column
    keeps its schema default.
    """
    cur = conn.execute(
        "INSERT INTO events (timestamp, headline, stage, persistence, "
        "event_date, mechanism_family, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            created_at,
            _str_field(event, "headline"),
            INTAKE_STAGE,
            INTAKE_PERSISTENCE,
            _coerce_date_str(event.get("event_date")),
            _str_field(event, "mechanism_family"),
            _str_field(event, "curator_notes"),
        ),
    )
    return int(cur.lastrowid)


def _insert_provenance_row(
    conn: sqlite3.Connection, event_id: int, prov: dict[str, Any],
) -> None:
    """Insert one ``event_provenance`` row keyed to ``event_id``."""
    conn.execute(
        "INSERT INTO event_provenance ("
        "event_id, source_type, source_publisher, source_url, "
        "source_published_at, mechanism_label_provenance, intake_path, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            prov["source_type"],
            prov["source_publisher"],
            prov["source_url"],
            prov["source_published_at"],
            prov["mechanism_label_provenance"],
            prov["intake_path"],
            prov["created_at"],
        ),
    )


# ---------------------------------------------------------------------------
# Guarded writer
# ---------------------------------------------------------------------------


def apply_curated_intake(
    *,
    yaml_path: str | None = None,
    events: list[dict[str, Any]] | None = None,
    db_path: str | None = None,
    confirm: bool = False,
    backup_path: str | None = None,
) -> dict[str, Any]:
    """Apply the intake plan when every gate passes.

    Without ``confirm=True`` this returns the plan plus a
    ``write_attempted=False`` envelope and writes nothing.  With
    ``confirm=True`` it still refuses (writing nothing) unless a
    ``backup_path`` distinct from the target is supplied and every event
    is acceptable; the refusal reason is surfaced on ``refuse_reason``.

    The writer first snapshots the target DB to ``backup_path`` (a restore
    point), then inserts every accepted event inside a single
    ``BEGIN IMMEDIATE`` transaction that rolls back on any error.
    """
    plan = plan_curated_intake(
        yaml_path=yaml_path, events=events, db_path=db_path,
    )
    insert_events = plan.pop("_insert_events", [])

    envelope: dict[str, Any] = {
        **plan,
        "write_attempted": False,
        "inserted_count":  0,
        "inserted":        [],
        "backup_path":     None,
        "refuse_reason":   None,
        "error":           None,
    }

    if not confirm:
        return envelope

    target = _resolve_db_path(db_path)

    if not backup_path:
        envelope["refuse_reason"] = (
            "--backup-path is required for --write (no restore point)"
        )
        return envelope
    if _same_path(backup_path, target):
        envelope["refuse_reason"] = (
            "backup_path must differ from the target database path"
        )
        return envelope
    if plan["validation_errors"] or plan["rejected"]:
        envelope["refuse_reason"] = (
            "refusing to write: one or more events failed validation or an "
            "intake guard (fix the worksheet and re-run; the writer is "
            "idempotent by source_url)"
        )
        return envelope
    if not insert_events:
        # Clean idempotent no-op — everything was already present.  Not a
        # refusal: leave refuse_reason None so the CLI exits 0.
        return envelope

    created_at = _now_iso()

    # Ensure the schema exists on the target, then snapshot it before any
    # mutation.  Rebind db.DB_FILE around init_db so the (idempotent)
    # schema-ensure lands on the target the writer is about to touch.
    import db as _db
    orig_db_file = _db.DB_FILE
    inserted: list[dict[str, Any]] = []
    try:
        _db.DB_FILE = target
        _db.init_db()

        try:
            shutil.copy2(target, backup_path)
        except OSError as exc:
            envelope["error"] = f"failed to write backup snapshot: {exc}"
            envelope["refuse_reason"] = (
                "could not create the backup snapshot; wrote nothing"
            )
            return envelope
        envelope["backup_path"] = backup_path

        # Autocommit + explicit BEGIN IMMEDIATE so a concurrent writer
        # serialises on the reserved lock and so every insert lives in one
        # transaction that rolls back together on any error.
        conn = sqlite3.connect(target, isolation_level=None, timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for event in insert_events:
                    event_id = _insert_event_row(
                        conn, event, created_at=created_at,
                    )
                    _insert_provenance_row(
                        conn, event_id,
                        _provenance_row_for_event(event, created_at=created_at),
                    )
                    inserted.append({
                        "event_id":   event_id,
                        "source_url": _str_field(event, "source_url"),
                    })
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — surface, do not crash the CLI
        envelope["error"] = f"{type(exc).__name__}: {exc}"
        envelope["write_attempted"] = False
        envelope["inserted_count"] = 0
        envelope["inserted"] = []
        return envelope
    finally:
        _db.DB_FILE = orig_db_file

    envelope["write_attempted"] = True
    envelope["inserted"] = inserted
    envelope["inserted_count"] = len(inserted)
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Drop private keys (the raw insert-event list) for display / JSON."""
    return {k: v for k, v in report.items() if not k.startswith("_")}


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(
        _public_report(report), indent=2, sort_keys=True, default=str,
    )


def _render_text(report: dict[str, Any]) -> str:
    is_write = "write_attempted" in report
    lines: list[str] = [
        "Curated event intake — "
        + ("write" if report.get("write_attempted") else "dry-run"),
        "",
        f"ok:               {report.get('ok')}",
        f"validated_count:  {report.get('validated_count')}",
        f"to_insert_count:  {report.get('to_insert_count')}",
        f"skipped_existing: {len(report.get('skipped_existing') or [])}",
        f"rejected:         {len(report.get('rejected') or [])}",
    ]

    for item in report.get("to_insert") or []:
        lines.append(
            f"  + {item.get('event_id')}: {item.get('source_url')}"
        )
    for item in report.get("skipped_existing") or []:
        lines.append(
            f"  = {item.get('event_id')}: {item.get('source_url')} "
            f"({item.get('reason')})"
        )
    for item in report.get("rejected") or []:
        lines.append(f"  x {item.get('event_id')}: {item.get('errors')}")

    for err in report.get("validation_errors") or []:
        lines.append(f"  ! {err}")

    if is_write:
        lines.append("")
        lines.append("Write:")
        lines.append(f"  backup_path:     {report.get('backup_path')}")
        lines.append(f"  write_attempted: {report.get('write_attempted')}")
        lines.append(f"  inserted_count:  {report.get('inserted_count')}")
        if report.get("refuse_reason"):
            lines.append(f"  refuse_reason:   {report.get('refuse_reason')}")
        if report.get("error"):
            lines.append(f"  error:           {report.get('error')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


_WRITE_GUIDANCE = (
    "Refusing to run: --write and --confirm must be supplied together.\n"
    "Dry-run is the safe default - invoke write mode with the full triple:\n"
    "  python scripts/curated_event_intake_apply.py --yaml WORKSHEET.yaml \\\n"
    "      --write --confirm --backup-path backups/pre-intake.db"
)

_BACKUP_GUIDANCE = (
    "Refusing to run: --write also requires --backup-path (a restore point\n"
    "distinct from the target database).  Example:\n"
    "  python scripts/curated_event_intake_apply.py --yaml WORKSHEET.yaml \\\n"
    "      --write --confirm --backup-path backups/pre-intake.db"
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run preview (default) or guarded write of curated YAML "
            "events into events + event_provenance.  Write mode requires "
            "--write, --confirm, and --backup-path together; it is "
            "idempotent by event_provenance.source_url and never mutates "
            "legacy rows."
        ),
    )
    parser.add_argument(
        "--yaml", dest="yaml_path", required=True,
        help="Path to the curated-event YAML worksheet.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help="Optional SQLite events.db path.  Defaults to db.DB_FILE.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explicit dry-run (this is also the default with no flags).",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Persist inserts.  Requires --confirm and --backup-path.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirm an explicit --write run.  Required together with --write.",
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help="Where to snapshot the target DB before writing (required for "
             "--write; must differ from the target).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    # --dry-run always wins, even if write flags are present, so an explicit
    # dry-run can never fall through to a write.
    if args.dry_run:
        report = plan_curated_intake(
            yaml_path=args.yaml_path, db_path=args.db_path,
        )
        report = _public_report(report)
    elif args.write or args.confirm:
        if not (args.write and args.confirm):
            print(_WRITE_GUIDANCE, file=sys.stderr)
            return 2
        if not args.backup_path:
            print(_BACKUP_GUIDANCE, file=sys.stderr)
            return 2
        report = apply_curated_intake(
            yaml_path=args.yaml_path, db_path=args.db_path,
            confirm=True, backup_path=args.backup_path,
        )
    else:
        report = plan_curated_intake(
            yaml_path=args.yaml_path, db_path=args.db_path,
        )
        report = _public_report(report)

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)

    # Write that refused (gate failed) or errored exits non-zero so a
    # wrapper / CI can detect the no-op.
    if "write_attempted" in report:
        if report.get("refuse_reason") or report.get("error"):
            return 1
        return 0
    # Dry-run: non-zero when the plan is not writable (validation / guard
    # failures) so the operator sees the worksheet needs fixing.
    return 0 if report.get("ok") else 1


__all__ = (
    "plan_curated_intake",
    "apply_curated_intake",
    "main",
    "INTAKE_STAGE",
    "INTAKE_PERSISTENCE",
    "INTAKE_PATH",
    "VALID_MECHANISM_LABEL_PROVENANCE",
    "SOURCE_TYPES_REQUIRING_URL",
)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""K3 — guarded curated_intake -> curated_observation promotion.

Turns a frozen-ledger batch of source-anchored ``curated_intake`` rows into
counted ``curated_observation`` rows so they become real event-study
OBSERVATIONS (they enter the analysis / coverage denominators) WITHOUT ever
becoming scoreable theses (``db.NON_THESIS_STAGES`` keeps them out of the
track record and the diagnostics outcome blocks).  This is the only path
that performs that transition.

It computes NO returns, fabricates NO thesis, and makes NO provider / LLM /
paid call.  The single market signal it writes is the primary ticker symbol
the curated candidate already named.

Two-phase, guarded-write contract (mirrors curated_event_intake_apply)
----------------------------------------------------------------------
* :func:`plan_promotion` is a pure read — it joins ``events`` +
  ``event_provenance`` + ``curated_candidates``, selects the rows whose
  ``source_url`` is in the frozen-ledger manifest, and classifies each into
  *to-promote* / *skipped (already promoted)* / *rejected (a gate failed)*.
  It never writes and never creates the DB file.
* :func:`apply_promotion` writes nothing unless ``confirm=True`` AND a
  ``backup_path`` distinct from the target is supplied AND no selected row is
  rejected.  It snapshots the DB first, then runs every UPDATE inside one
  ``BEGIN IMMEDIATE`` transaction that rolls back together on any error.

Promotion gates (ALL must pass)
-------------------------------
* ``events.stage == "curated_intake"`` (a row already promoted is *skipped*,
  not re-promoted — the path is idempotent);
* ``event_provenance.mechanism_label_provenance == "curated"`` (a human read
  the label off the source; never an LLM-inferred ``model`` label);
* ``events.mechanism_family`` is in ``mechanism_family.FAMILY_IDS``;
* a matching ``curated_candidates`` row (by ``source_event_id``) carries a
  non-empty ``primary_ticker``;
* the row's ``source_url`` is in the supplied frozen-ledger manifest.

What promotion writes
---------------------
* ``events.stage``            -> ``"curated_observation"``
* ``events.market_tickers``   -> ``[{"symbol": <primary>, "role": "primary"}]``
* ``event_provenance.intake_path`` -> ``"curated_promoted"``
* ``curated_candidates.status``    -> ``"promoted"``

Usage::

    python scripts/curated_observation_promote.py --manifest frozen.txt          # dry-run
    python scripts/curated_observation_promote.py --manifest frozen.txt --json    # dry-run JSON
    python scripts/curated_observation_promote.py --manifest frozen.txt \\
        --write --confirm --backup-path backups/pre-promote.db                    # guarded write
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from typing import Any, Iterable, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402
from mechanism_family import FAMILY_IDS  # noqa: E402


# Stage / status / path constants — the canonical observation stage lives in
# ``db`` so promoter and aggregators key off the SAME object.
OBSERVATION_STAGE = db.CURATED_OBSERVATION_STAGE
INTAKE_STAGE = db.CURATED_INTAKE_STAGE
PROMOTED_INTAKE_PATH = "curated_promoted"
PROMOTED_STATUS = "promoted"
REQUIRED_LABEL_PROVENANCE = "curated"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(db_path: str | None) -> str:
    if db_path is not None:
        return db_path
    return db.get_db_path()


def _same_path(a: str, b: str) -> bool:
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.abspath(a) == os.path.abspath(b)


def _coerce_manifest(manifest: Iterable[str] | None) -> set[str]:
    """Normalise the frozen-ledger manifest to a set of non-blank urls."""
    if not manifest:
        return set()
    return {
        s.strip() for s in manifest
        if isinstance(s, str) and s.strip()
    }


def _primary_ticker_for_event(
    conn: sqlite3.Connection, event_id: int,
) -> str | None:
    """First non-empty ``curated_candidates.primary_ticker`` for the event."""
    try:
        rows = conn.execute(
            "SELECT primary_ticker FROM curated_candidates "
            "WHERE source_event_id = ? ORDER BY id",
            (event_id,),
        ).fetchall()
    except sqlite3.Error:
        return None
    for r in rows:
        val = r[0]
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _gate_errors(
    conn: sqlite3.Connection, *, stage: str, label_prov: str,
    mechanism_family: str, primary_ticker: str | None,
) -> list[str]:
    """Promotion-gate errors for one manifest-selected row (empty == ok).

    The caller has already handled the ``already promoted`` (skip) case;
    this only runs on a row we intend to promote.
    """
    errors: list[str] = []
    if stage != INTAKE_STAGE:
        errors.append(
            f"only {INTAKE_STAGE!r} rows are promotable; stage is {stage!r}"
        )
    if label_prov != REQUIRED_LABEL_PROVENANCE:
        errors.append(
            "mechanism_label_provenance must be "
            f"{REQUIRED_LABEL_PROVENANCE!r}; got {label_prov!r}"
        )
    if mechanism_family not in FAMILY_IDS:
        errors.append(
            f"mechanism_family {mechanism_family!r} is not in FAMILY_IDS"
        )
    if not (isinstance(primary_ticker, str) and primary_ticker.strip()):
        errors.append(
            "no matching curated_candidates row with a primary_ticker"
        )
    return errors


def _market_tickers_value(primary_ticker: str) -> str:
    """The single honest market_tickers payload: the primary symbol only.

    No beneficiary / loser roles, no return fields — a promoted observation
    carries no thesis.  ``_primary_ticker`` (event_study_validation) reads the
    first symbol, upper-cased; store it upper-cased so the stored value and
    the read value agree.
    """
    return json.dumps(
        [{"symbol": primary_ticker.strip().upper(), "role": "primary"}]
    )


# ---------------------------------------------------------------------------
# Dry-run planner — pure read
# ---------------------------------------------------------------------------


def plan_promotion(
    *, db_path: str | None = None, manifest: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Classify manifest-selected rows into promote / skip / reject.  Read-only."""
    target = _resolve_db_path(db_path)
    wanted = _coerce_manifest(manifest)

    to_promote: list[dict[str, Any]] = []
    promote_full: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    if not wanted or not target or not os.path.exists(target):
        return {
            "ok": True, "to_promote": to_promote, "to_promote_count": 0,
            "skipped": skipped, "rejected": rejected, "_promote": promote_full,
        }

    try:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    except sqlite3.Error:
        return {
            "ok": True, "to_promote": to_promote, "to_promote_count": 0,
            "skipped": skipped, "rejected": rejected, "_promote": promote_full,
        }
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT e.id AS id, e.stage AS stage, "
                "e.mechanism_family AS mechanism_family, "
                "p.source_url AS source_url, "
                "p.mechanism_label_provenance AS label_prov "
                "FROM events e "
                "JOIN event_provenance p ON p.event_id = e.id "
                "ORDER BY e.id"
            ).fetchall()
        except sqlite3.Error:
            rows = []

        for r in rows:
            url = r["source_url"]
            if not (isinstance(url, str) and url in wanted):
                continue  # not in the frozen ledger — never touched
            stage = (r["stage"] or "").strip()
            if stage == OBSERVATION_STAGE:
                skipped.append({
                    "event_id": r["id"], "source_url": url,
                    "reason": "already promoted (curated_observation)",
                })
                continue
            primary = _primary_ticker_for_event(conn, int(r["id"]))
            errs = _gate_errors(
                conn,
                stage=stage,
                label_prov=(r["label_prov"] or "").strip(),
                mechanism_family=(r["mechanism_family"] or "").strip(),
                primary_ticker=primary,
            )
            if errs:
                rejected.append({"event_id": r["id"], "source_url": url, "errors": errs})
                continue
            to_promote.append({
                "event_id": r["id"], "source_url": url, "primary_ticker": primary,
            })
            promote_full.append({
                "event_id": int(r["id"]), "source_url": url, "primary_ticker": primary,
            })
    finally:
        conn.close()

    return {
        "ok": not rejected,
        "to_promote": to_promote,
        "to_promote_count": len(to_promote),
        "skipped": skipped,
        "rejected": rejected,
        "_promote": promote_full,
    }


# ---------------------------------------------------------------------------
# Guarded writer
# ---------------------------------------------------------------------------


def apply_promotion(
    *, db_path: str | None = None, manifest: Iterable[str] | None = None,
    confirm: bool = False, backup_path: str | None = None,
) -> dict[str, Any]:
    """Apply the promotion plan when every gate passes.  Writes nothing
    without ``confirm=True`` + a distinct ``backup_path`` + a reject-free plan."""
    plan = plan_promotion(db_path=db_path, manifest=manifest)
    promote_rows = plan.pop("_promote", [])

    envelope: dict[str, Any] = {
        **plan,
        "write_attempted": False,
        "promoted_count": 0,
        "promoted": [],
        "backup_path": None,
        "refuse_reason": None,
        "error": None,
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
    if plan["rejected"]:
        envelope["refuse_reason"] = (
            "refusing to write: one or more selected rows failed a promotion "
            "gate (fix the batch and re-run; the promoter is idempotent)"
        )
        return envelope
    if not promote_rows:
        return envelope  # clean no-op (nothing selected / all already promoted)

    try:
        shutil.copy2(target, backup_path)
    except OSError as exc:
        envelope["error"] = f"failed to write backup snapshot: {exc}"
        envelope["refuse_reason"] = "could not create the backup snapshot; wrote nothing"
        return envelope
    envelope["backup_path"] = backup_path

    promoted: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(target, isolation_level=None, timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for row in promote_rows:
                    eid = int(row["event_id"])
                    conn.execute(
                        "UPDATE events SET stage = ?, market_tickers = ? WHERE id = ?",
                        (OBSERVATION_STAGE, _market_tickers_value(row["primary_ticker"]), eid),
                    )
                    conn.execute(
                        "UPDATE event_provenance SET intake_path = ? WHERE event_id = ?",
                        (PROMOTED_INTAKE_PATH, eid),
                    )
                    conn.execute(
                        "UPDATE curated_candidates SET status = ? WHERE source_event_id = ?",
                        (PROMOTED_STATUS, eid),
                    )
                    promoted.append({"event_id": eid, "source_url": row["source_url"]})
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — surface, do not crash the CLI
        envelope["error"] = f"{type(exc).__name__}: {exc}"
        envelope["write_attempted"] = False
        envelope["promoted_count"] = 0
        envelope["promoted"] = []
        return envelope

    envelope["write_attempted"] = True
    envelope["promoted"] = promoted
    envelope["promoted_count"] = len(promoted)
    return envelope


# ---------------------------------------------------------------------------
# Manifest loading + rendering
# ---------------------------------------------------------------------------


def _load_manifest(path: str) -> set[str]:
    """Load the frozen-ledger manifest: a YAML/JSON list, a dict with a
    ``source_urls`` list, or a plain text file (one url per line, ``#``
    comments allowed)."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml
        parsed = yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        parsed = None
    if isinstance(parsed, list):
        return _coerce_manifest(parsed)
    if isinstance(parsed, dict) and isinstance(parsed.get("source_urls"), list):
        return _coerce_manifest(parsed["source_urls"])
    return {
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _public(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if not k.startswith("_")}


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(_public(report), indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    is_write = "write_attempted" in report
    lines = [
        "Curated observation promotion — "
        + ("write" if report.get("write_attempted") else "dry-run"),
        "",
        f"ok:               {report.get('ok')}",
        f"to_promote_count: {report.get('to_promote_count')}",
        f"skipped:          {len(report.get('skipped') or [])}",
        f"rejected:         {len(report.get('rejected') or [])}",
    ]
    for item in report.get("to_promote") or []:
        lines.append(f"  + {item.get('event_id')}: {item.get('source_url')} "
                     f"({item.get('primary_ticker')})")
    for item in report.get("skipped") or []:
        lines.append(f"  = {item.get('event_id')}: {item.get('reason')}")
    for item in report.get("rejected") or []:
        lines.append(f"  x {item.get('event_id')}: {item.get('errors')}")
    if is_write:
        lines += [
            "",
            "Write:",
            f"  backup_path:     {report.get('backup_path')}",
            f"  write_attempted: {report.get('write_attempted')}",
            f"  promoted_count:  {report.get('promoted_count')}",
        ]
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
    "Dry-run is the safe default; invoke write mode with the full triple:\n"
    "  python scripts/curated_observation_promote.py --manifest M.txt \\\n"
    "      --write --confirm --backup-path backups/pre-promote.db"
)
_BACKUP_GUIDANCE = (
    "Refusing to run: --write also requires --backup-path (a restore point\n"
    "distinct from the target database)."
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run preview (default) or guarded promotion of frozen "
            "curated_intake rows to curated_observation.  Write mode requires "
            "--write, --confirm, and --backup-path together."
        ),
    )
    parser.add_argument("--manifest", dest="manifest", required=True,
                        help="Frozen-ledger manifest of source_urls "
                             "(YAML/JSON list, {source_urls:[...]}, or one per line).")
    parser.add_argument("--db-path", dest="db_path", default=None,
                        help="Optional SQLite events.db path.  Defaults to db.DB_FILE.")
    parser.add_argument("--json", action="store_true",
                        help="Emit structured JSON instead of the text report.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Explicit dry-run (also the default with no flags).")
    parser.add_argument("--write", action="store_true",
                        help="Persist promotions.  Requires --confirm and --backup-path.")
    parser.add_argument("--confirm", action="store_true",
                        help="Confirm an explicit --write run.")
    parser.add_argument("--backup-path", dest="backup_path", default=None,
                        help="Where to snapshot the DB before writing (required "
                             "for --write; must differ from the target).")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    try:
        manifest = _load_manifest(args.manifest)
    except OSError as exc:
        print(f"failed to read --manifest {args.manifest!r}: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        report = _public(plan_promotion(db_path=args.db_path, manifest=manifest))
    elif args.write or args.confirm:
        if not (args.write and args.confirm):
            print(_WRITE_GUIDANCE, file=sys.stderr)
            return 2
        if not args.backup_path:
            print(_BACKUP_GUIDANCE, file=sys.stderr)
            return 2
        report = apply_promotion(
            db_path=args.db_path, manifest=manifest,
            confirm=True, backup_path=args.backup_path,
        )
    else:
        report = _public(plan_promotion(db_path=args.db_path, manifest=manifest))

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)

    if "write_attempted" in report:
        if report.get("refuse_reason") or report.get("error"):
            return 1
        return 0
    return 0 if report.get("ok") else 1


__all__ = (
    "plan_promotion",
    "apply_promotion",
    "main",
    "OBSERVATION_STAGE",
    "INTAKE_STAGE",
    "PROMOTED_INTAKE_PATH",
    "PROMOTED_STATUS",
)


if __name__ == "__main__":
    sys.exit(main())

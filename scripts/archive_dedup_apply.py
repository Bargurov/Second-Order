#!/usr/bin/env python3
"""Dry-run planner and guarded writer for exact (headline, event_date) dedup.

The archive carries duplicate ``events`` rows that share an identical
``(headline, event_date)`` pair — the same news item analyzed / ingested
more than once, plus a block of seeded test rows.  Each duplicate is a
distinct row in the ``events`` table, so the statistical-readiness
denominator and any future FDR pool double-count them.  This script
collapses each **exact** ``(headline, event_date)`` cluster down to one
canonical row.

Two-phase, guarded-write contract (mirrors ``event_date_backfill.py``)
----------------------------------------------------------------------
* :func:`plan_dedup` is a pure read — it issues only ``SELECT`` and
  delegates to the read-only :mod:`scripts.stat_validation_readiness_report`
  to label each row's readiness.  It returns a deterministic keep/remove
  plan plus the projected post-dedup readiness denominator.
* :func:`apply_dedup` writes nothing unless ``confirm=True``.  Even with
  ``confirm=True`` it refuses to delete unless **both** safety gates pass:
    1. a restore-valid ``events-*.db`` backup exists whose mtime is at
       least as new as the target DB (the operator backed up the current
       state), and
    2. the pre-delete reference scan finds no real inbound event
       reference to any removed id.
  The delete runs inside a single ``BEGIN IMMEDIATE`` transaction that
  serialises against a concurrent uvicorn writer and rolls back on any
  error.  A second run is a no-op: once each cluster has one row the
  ``HAVING COUNT(*) >= 2`` group vanishes.

What this script deliberately does NOT do
------------------------------------------
* It never merges *near-duplicate* / variant headlines — grouping is on
  the exact ``(headline, event_date)`` pair, so
  ``"Fed speakers rotate"`` and ``"Fed speakers rotate on inflation
  commentary"`` stay distinct events.
* It never removes a cluster's last row, and never touches singleton
  rows — only the non-canonical members of a ``COUNT(*) >= 2`` exact
  cluster are candidates for deletion.
* No provider, ``yfinance``, ``market_check``, ``market_data``,
  ``price_cache`` (production module), LLM, or FastAPI surface — read
  and delete speak raw ``sqlite3`` only.

Usage::

    python scripts/archive_dedup_apply.py                 # dry-run (default)
    python scripts/archive_dedup_apply.py --dry-run --json
    python scripts/archive_dedup_apply.py --db-path snapshot.db --json
    python scripts/archive_dedup_apply.py --write --confirm   # guarded write
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Read-only readiness labeller.  Bound at module level so a unit test can
# patch the seam with a synthetic readiness map instead of paying the
# price_cache walk.
from scripts.stat_validation_readiness_report import (  # noqa: E402
    summarize_readiness as _summarize_readiness,
)
from scripts.backup_restore_check import (  # noqa: E402
    find_latest_backup,
    restore_check,
)


_TIEBREAK_DESC = "fully_ready desc, n_tickers desc, id asc"

# Columns in non-``events`` tables that, by name, denote a foreign
# reference to ``events.id``.  Restricting the scan to these names is
# deliberate: a generic "any int column that overlaps a remove-id"
# scan false-positives on unrelated primary keys (``news_clusters.id``),
# the news-layer FK (``news_headline_assignments.cluster_id``), and
# version integers (``movers_cache.compute_version``).  None of those
# reference the analyzed-events table.
_EVENT_FK_COLUMN_NAMES: tuple[str, ...] = ("event_id", "event_ids")

# Text / JSON columns that can *embed* event ids inside a payload rather
# than expose them as a typed FK column.  Scanned token-wise for any
# removed id.
_EMBEDDED_REFERENCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "saved_studies": ("config_json", "description"),
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def _ticker_symbol_count(raw_market_tickers: Any) -> int:
    """Count non-empty ``symbol`` entries in the stored market_tickers JSON.

    Tolerant of every malformed shape the archive carries (None, empty,
    unparseable JSON, non-list payload, dictless entries, blank symbols)
    — each degrades to ``0`` cleanly.
    """
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return 0
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return 0
    if not isinstance(parsed, list):
        return 0
    count = 0
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if isinstance(sym, str) and sym.strip():
            count += 1
    return count


def _load_readiness_map(*, db_path: str | None) -> dict[int, bool]:
    """Return ``{event_id: fully_ready}`` for every event in the archive.

    Delegates to the read-only readiness report with an effectively
    unlimited per-event cap so the map covers the whole archive, not the
    report's truncated sample.  On any failure returns an empty map; the
    tiebreak then degrades to ``(n_tickers desc, id asc)`` — still fully
    deterministic.
    """
    try:
        report = _summarize_readiness(db_path=db_path, limit=10**12)
    except Exception:  # noqa: BLE001 — operator-visible degradation
        return {}
    out: dict[int, bool] = {}
    for entry in report.get("events") or []:
        ev_id = entry.get("event_id")
        if isinstance(ev_id, int):
            out[ev_id] = bool(entry.get("fully_ready"))
    return out


def _canonical_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the keep row under the readiness-aware deterministic tiebreak.

    Sort key: ``fully_ready`` first (ready rows sort ahead), then more
    tickers, then smallest id.  Every component is total and
    deterministic, so the canonical choice never depends on row order
    from SQLite.  The preflight confirmed this rule never drops a unique
    ready row; the ``fully_ready`` term makes that guarantee explicit
    rather than incidental.
    """
    return min(
        rows,
        key=lambda r: (
            0 if r["fully_ready"] else 1,
            -int(r["n_tickers"]),
            int(r["id"]),
        ),
    )


# ---------------------------------------------------------------------------
# Dry-run planner — pure read
# ---------------------------------------------------------------------------


def plan_dedup(*, db_path: str | None = None) -> dict[str, Any]:
    """Return a deterministic exact ``(headline, event_date)`` dedup plan.

    Read-only: a single ``SELECT`` over ``events`` plus the read-only
    readiness labeller.  See the module docstring for the contract.

    Returns a dict with: ``exact_match_only`` (always True), ``tiebreak``,
    ``cluster_count``, ``keep_ids``, ``remove_ids``, ``remove_count``,
    ``clusters`` (per-cluster keep/remove detail), and
    ``readiness_projection`` (pre / post denominator + ready counts).
    """
    path = _resolve_db_path(db_path)
    empty = _empty_plan()
    if path is None:
        return empty

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return empty
    try:
        try:
            rows = conn.execute(
                "SELECT id, headline, event_date, market_tickers FROM events "
                "ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    readiness = _load_readiness_map(db_path=path)

    # Group by EXACT (headline, event_date) over non-blank pairs only.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    total_events = 0
    pre_ready = 0
    for raw_id, headline, event_date, market_tickers in rows:
        try:
            ev_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        total_events += 1
        ready = bool(readiness.get(ev_id, False))
        if ready:
            pre_ready += 1
        if not (isinstance(headline, str) and headline.strip()):
            continue
        if not (isinstance(event_date, str) and event_date.strip()):
            continue
        key = (headline, event_date)
        groups.setdefault(key, []).append({
            "id":          ev_id,
            "n_tickers":   _ticker_symbol_count(market_tickers),
            "fully_ready": ready,
        })

    clusters: list[dict[str, Any]] = []
    keep_ids: list[int] = []
    remove_ids: list[int] = []
    removed_ready = 0
    for (headline, event_date), members in groups.items():
        if len(members) < 2:
            continue  # singleton — never touched
        keep = _canonical_row(members)
        keep_ids.append(keep["id"])
        member_ids = sorted(m["id"] for m in members)
        removed = [i for i in member_ids if i != keep["id"]]
        remove_ids.extend(removed)
        removed_ready += sum(
            1 for m in members
            if m["id"] != keep["id"] and m["fully_ready"]
        )
        clusters.append({
            "headline":    headline,
            "event_date":  event_date,
            "count":       len(members),
            "keep_id":     keep["id"],
            "keep_ready":  keep["fully_ready"],
            "remove_ids":  removed,
            "rows":        sorted(members, key=lambda m: m["id"]),
        })

    clusters.sort(key=lambda c: (c["event_date"], c["headline"]))
    keep_ids.sort()
    remove_ids.sort()

    post_total = total_events - len(remove_ids)
    post_ready = pre_ready - removed_ready

    return {
        "exact_match_only": True,
        "tiebreak":         _TIEBREAK_DESC,
        "cluster_count":    len(clusters),
        "keep_ids":         keep_ids,
        "remove_ids":       remove_ids,
        "remove_count":     len(remove_ids),
        "clusters":         clusters,
        "readiness_projection": {
            "pre_total":     total_events,
            "pre_ready":     pre_ready,
            "pre_rate":      round(pre_ready / total_events, 4) if total_events else None,
            "removed_total": len(remove_ids),
            "removed_ready": removed_ready,
            "post_total":    post_total,
            "post_ready":    post_ready,
            "post_rate":     round(post_ready / post_total, 4) if post_total else None,
        },
    }


def _empty_plan() -> dict[str, Any]:
    return {
        "exact_match_only": True,
        "tiebreak":         _TIEBREAK_DESC,
        "cluster_count":    0,
        "keep_ids":         [],
        "remove_ids":       [],
        "remove_count":     0,
        "clusters":         [],
        "readiness_projection": {
            "pre_total":     0,
            "pre_ready":     0,
            "pre_rate":      None,
            "removed_total": 0,
            "removed_ready": 0,
            "post_total":    0,
            "post_ready":    0,
            "post_rate":     None,
        },
    }


# ---------------------------------------------------------------------------
# Pre-delete reference scan
# ---------------------------------------------------------------------------


def _ints_in_value(value: Any) -> set[int]:
    """Extract candidate event ids from an FK-column value.

    Handles a bare int, or a string holding a CSV / JSON list of ids
    (``"12,13"`` / ``"[12, 13]"``).  Word-boundary token extraction keeps
    ``"120"`` from matching inside ``"1200"``.
    """
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, str) and value:
        return {int(tok) for tok in re.findall(r"\b\d+\b", value)}
    return set()


def find_reference_conflicts(
    *, db_path: str | None, remove_ids: Iterable[int],
) -> list[dict[str, Any]]:
    """Return inbound references to any ``remove_ids`` row, or ``[]``.

    Scans only the references that genuinely denote ``events.id``:
    columns literally named ``event_id`` / ``event_ids`` in other tables,
    and the known embedded-payload columns (``saved_studies``).  This
    targeted scope avoids the false positives a blanket int-overlap scan
    produces on unrelated primary keys, news-layer FKs, and version
    integers.  Read-only.

    Event->event links are deliberately NOT scanned: related-event
    linking and the event cascade are computed at read time from the
    headline (Jaccard in ``db.find_related_events`` /
    ``db.get_event_cascade``), and ``revisit_snapshots`` stores the
    event's own per-day market snapshots keyed by ``day`` — no events
    row persists a sibling event's id, so deleting a duplicate cannot
    orphan a stored reference.  The read-time surfaces simply recompute
    over the deduped set.
    """
    remove_set = {int(i) for i in remove_ids}
    if not remove_set:
        return []
    path = _resolve_db_path(db_path)
    if path is None:
        return []
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return []

    conflicts: list[dict[str, Any]] = []
    try:
        try:
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            ]
        except sqlite3.Error:
            return []

        for table in tables:
            if table == "events":
                continue
            try:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
            except sqlite3.Error:
                continue

            # 1. Typed FK columns named event_id / event_ids.
            for col in cols:
                if col.lower() not in _EVENT_FK_COLUMN_NAMES:
                    continue
                try:
                    values = conn.execute(f"SELECT {col} FROM {table}").fetchall()
                except sqlite3.Error:
                    continue
                hit_ids: set[int] = set()
                for (v,) in values:
                    hit_ids |= _ints_in_value(v) & remove_set
                if hit_ids:
                    conflicts.append({
                        "table":  table,
                        "column": col,
                        "kind":   "typed_fk",
                        "referenced_remove_ids": sorted(hit_ids),
                    })

            # 2. Embedded-payload columns (token scan).
            embed_cols = _EMBEDDED_REFERENCE_COLUMNS.get(table, ())
            present = [c for c in embed_cols if c in cols]
            if present:
                try:
                    payload_rows = conn.execute(
                        f"SELECT {','.join(present)} FROM {table}"
                    ).fetchall()
                except sqlite3.Error:
                    payload_rows = []
                hit_ids = set()
                for row in payload_rows:
                    for cell in row:
                        if isinstance(cell, str) and cell:
                            hit_ids |= _ints_in_value(cell) & remove_set
                if hit_ids:
                    conflicts.append({
                        "table":  table,
                        "column": ",".join(present),
                        "kind":   "embedded_payload",
                        "referenced_remove_ids": sorted(hit_ids),
                    })
    finally:
        conn.close()
    return conflicts


# ---------------------------------------------------------------------------
# Fresh-backup gate
# ---------------------------------------------------------------------------


def check_fresh_backup(
    *, db_path: str | None, backup_dir: str = "backups",
) -> dict[str, Any]:
    """Return ``{ok, reason, backup_path, backup_mtime, db_mtime}``.

    A backup is *fresh* when a restore-valid ``events-*.db`` exists whose
    mtime is at least as new as the target DB — i.e. the operator backed
    up the archive's *current* state.  Read-only.
    """
    path = _resolve_db_path(db_path)
    result: dict[str, Any] = {
        "ok":           False,
        "reason":       "",
        "backup_path":  None,
        "backup_mtime": None,
        "db_mtime":     None,
    }
    if path is None or not Path(path).exists():
        result["reason"] = "target database not found"
        return result

    db_mtime = Path(path).stat().st_mtime
    result["db_mtime"] = db_mtime

    latest = find_latest_backup(Path(backup_dir))
    if latest is None:
        result["reason"] = f"no events-*.db backup found in {backup_dir}/"
        return result
    result["backup_path"]  = str(latest)
    result["backup_mtime"] = latest.stat().st_mtime

    if latest.stat().st_mtime < db_mtime:
        result["reason"] = (
            "latest backup is older than the live database - take a fresh "
            "backup of the current archive before --write"
        )
        return result

    restore = restore_check(backup_path=latest, cleanup=True)
    if not restore.get("ok"):
        result["reason"] = (
            "latest backup failed restore validation: "
            + "; ".join(restore.get("errors") or ["unknown error"])
        )
        return result

    result["ok"] = True
    result["reason"] = "fresh restore-valid backup present"
    return result


# ---------------------------------------------------------------------------
# Guarded writer
# ---------------------------------------------------------------------------


def apply_dedup(
    *,
    db_path: str | None = None,
    confirm: bool = False,
    backup_dir: str = "backups",
    require_fresh_backup: bool = True,
) -> dict[str, Any]:
    """Apply the dedup plan when ``confirm=True`` and both gates pass.

    Without ``confirm=True`` this returns the plan plus a
    ``write_attempted=False`` envelope and writes nothing.  With
    ``confirm=True`` it still refuses (writing nothing) unless the
    fresh-backup gate and the reference scan both pass; the refusal
    reason is surfaced on ``refuse_reason``.  The delete runs in a single
    ``BEGIN IMMEDIATE`` transaction and rolls back on any error.
    """
    plan = plan_dedup(db_path=db_path)
    remove_ids = list(plan.get("remove_ids") or [])

    conflicts = find_reference_conflicts(db_path=db_path, remove_ids=remove_ids)
    # Evaluate the fresh-backup gate lazily: an empty plan has nothing to
    # back up, so it should never pay for the restore_check copy.
    if not remove_ids:
        fresh = {"ok": True, "reason": "no removals planned; backup gate not evaluated"}
    elif not require_fresh_backup:
        fresh = {"ok": True, "reason": "fresh-backup gate disabled"}
    else:
        fresh = check_fresh_backup(db_path=db_path, backup_dir=backup_dir)

    envelope = {
        **plan,
        "write_attempted": False,
        "applied_count":   0,
        "deleted_ids":     [],
        "reference_conflicts": conflicts,
        "fresh_backup":    fresh,
        "refuse_reason":   None,
    }

    if not confirm:
        return envelope
    if not remove_ids:
        # Clean no-op: nothing to dedup.  This is NOT a refusal — leave
        # refuse_reason None so the CLI exits 0 (an idempotent re-run
        # after a successful dedup lands here).
        return envelope
    if conflicts:
        envelope["refuse_reason"] = (
            "pre-delete reference scan found inbound event references; "
            "refusing to delete"
        )
        return envelope
    if require_fresh_backup and not fresh.get("ok"):
        envelope["refuse_reason"] = f"fresh-backup gate failed: {fresh.get('reason')}"
        return envelope

    path = _resolve_db_path(db_path)
    deleted: list[int] = []
    # Autocommit + explicit BEGIN IMMEDIATE so a concurrent uvicorn
    # writer serialises on the reserved lock rather than racing the read.
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for ev_id in remove_ids:
                cur = conn.execute(
                    "DELETE FROM events WHERE id = ?", (ev_id,),
                )
                if cur.rowcount > 0:
                    deleted.append(ev_id)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    envelope["write_attempted"] = True
    envelope["applied_count"]   = len(deleted)
    envelope["deleted_ids"]     = sorted(deleted)
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    is_write = "write_attempted" in report
    proj = report.get("readiness_projection") or {}
    lines: list[str] = [
        "Archive exact (headline, event_date) dedup "
        + ("write" if report.get("write_attempted") else "dry-run"),
        "",
        f"exact_match_only: {report.get('exact_match_only')}",
        f"tiebreak:         {report.get('tiebreak')}",
        f"clusters:         {report.get('cluster_count')}",
        f"remove_count:     {report.get('remove_count')}",
        "",
        "Readiness projection:",
        f"  pre:  {proj.get('pre_ready')}/{proj.get('pre_total')} "
        f"({proj.get('pre_rate')})",
        f"  post: {proj.get('post_ready')}/{proj.get('post_total')} "
        f"({proj.get('post_rate')})",
        f"  removed_total={proj.get('removed_total')} "
        f"removed_ready={proj.get('removed_ready')}",
        "",
    ]

    clusters = report.get("clusters") or []
    lines.append(f"Clusters ({len(clusters)}):")
    for c in clusters:
        head = (c["headline"][:60] + "...") if len(c["headline"]) > 63 else c["headline"]
        lines.append(
            f"  {c['event_date']} count={c['count']:>2} "
            f"keep={c['keep_id']} (ready={c['keep_ready']}) "
            f"remove={c['remove_ids']}"
        )
        lines.append(f"      {head}")
    lines.append("")

    lines.append(f"keep_ids ({len(report.get('keep_ids') or [])}):   {report.get('keep_ids')}")
    lines.append(f"remove_ids ({len(report.get('remove_ids') or [])}): {report.get('remove_ids')}")
    lines.append("")

    if is_write:
        fresh = report.get("fresh_backup") or {}
        conflicts = report.get("reference_conflicts") or []
        lines.append("Write safety:")
        lines.append(f"  fresh_backup.ok:   {fresh.get('ok')} ({fresh.get('reason')})")
        lines.append(f"  reference_conflicts: {len(conflicts)}")
        for c in conflicts:
            lines.append(
                f"    - {c['table']}.{c['column']} ({c['kind']}) "
                f"-> {c['referenced_remove_ids']}"
            )
        lines.append(f"  write_attempted:   {report.get('write_attempted')}")
        lines.append(f"  applied_count:     {report.get('applied_count')}")
        if report.get("refuse_reason"):
            lines.append(f"  refuse_reason:     {report.get('refuse_reason')}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


_WRITE_GUIDANCE = (
    "Refusing to run: --write and --confirm must be supplied together.\n"
    "Dry-run is the safe default - invoke write mode with the full pair:\n"
    "  python scripts/archive_dedup_apply.py --write --confirm [--db-path PATH]\n"
    "The writer additionally refuses unless a fresh restore-valid backup "
    "exists and the pre-delete reference scan is clean."
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run preview (default) or guarded write of an exact "
            "(headline, event_date) dedup of the events archive.  Write "
            "mode requires --write and --confirm together, plus a fresh "
            "backup and a clean reference scan."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explicit dry-run (this is also the default with no flags).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help="Optional SQLite events.db path.  Defaults to db.DB_FILE.",
    )
    parser.add_argument(
        "--backup-dir", dest="backup_dir", default="backups",
        help="Directory searched for the fresh-backup gate (default: backups/).",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Persist deletions.  Requires --confirm; either alone exits non-zero.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirm an explicit --write run.  Required together with --write.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    # --dry-run always wins, even if write flags are present, so an
    # explicit dry-run can never fall through to a write.
    if args.dry_run:
        report = plan_dedup(db_path=args.db_path)
    elif args.write != args.confirm:
        print(_WRITE_GUIDANCE, file=sys.stderr)
        return 2
    elif args.write and args.confirm:
        report = apply_dedup(db_path=args.db_path, confirm=True,
                             backup_dir=args.backup_dir)
    else:
        report = plan_dedup(db_path=args.db_path)

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)

    # A confirmed write that refused (gate failed) exits non-zero so a
    # wrapper/CI can detect the no-op.
    if report.get("write_attempted") is False and report.get("refuse_reason"):
        return 1
    return 0


__all__ = (
    "plan_dedup",
    "apply_dedup",
    "find_reference_conflicts",
    "check_fresh_backup",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

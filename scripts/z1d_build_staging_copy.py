#!/usr/bin/env python3
"""AD1 - copy-build-then-swap rehearsal for Z1D live staging (no live swap).

The future live promotion process is:

    1. Stop the app / ensure no concurrent writer is bound to live events.db.
    2. Back up live events.db.
    3. Build a promoted working copy from the live DB.
    4. Verify the working copy.
    5. Atomically replace live events.db with the verified copy -- ONLY after
       explicit operator approval.
    6. Keep the rollback backup.

This script implements and verifies steps 2-4 ONLY.  It never performs step 5:
it does not replace events.db, does not write an auto-swap command, and prints
the swap as a NOT-EXECUTED operator checklist.  Step 1 (no concurrent writer) is
the operator's responsibility; this script reads the source DB read-only and
re-hashes it before and after the build to show the build itself mutated nothing,
but it cannot stop another process from writing live -- that is design step 1.

It is pure orchestration over the committed AC1 gate
(``scripts/z1d_live_staging_promotion.py``): it copies the source to a backup,
copies the backup to a working copy, runs the AC1 apply on the WORKING COPY ONLY
(which already hard-refuses the live archive and uses the free-only backfill /
densify by contract), then verifies the working copy and emits a swap-ready
verdict.  It does not weaken the AC1 live refusal and references no paid path.

Gates (a build proceeds only when all hold):

* ``--ack-live-staging`` plus explicit ``--backup-path`` and
  ``--working-copy-path``.
* The backup and working-copy paths are NOT the live archive, and source /
  backup / working are three DISTINCT paths -- so the AC1 apply can never mutate
  the rollback backup or the source.
* The required exclusions (steel proclamation 9705, section 301) are applied and
  there are no unexcluded collisions (reused AC1 plan).

The working copy is swap-ready only when, in addition, the source stayed
byte-identical, the backup matches the source, the working copy passes an
integrity check, the staged ``z1a_candidate_pack`` rows are present only in the
working copy, the analysis denominators exclude them, the default ``/events``
listing hides them (explicit stage surfaces them), there are no duplicate
candidate source_urls, and the delisted X ticker did not fail the build.

Every output is a descriptive build / readiness measurement on a non-promoted
copy -- not a directional, predictive, or statistical-importance claim.

Usage::

    # read-only dry run (safe against the live archive)
    python scripts/z1d_build_staging_copy.py --dry-run \\
        --source-db events.db \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml

    # build + verify a working copy (live is never swapped)
    python scripts/z1d_build_staging_copy.py --build-copy \\
        --source-db events.db \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml \\
        --backup-path backups/events_z1d_20260609.db \\
        --working-copy-path backups/events_z1d_20260609_working.db \\
        --ack-live-staging \\
        --exclude-candidate section232-steel-proclamation-9705-2018-03-08 \\
        --exclude-candidate section301-china-tariff-increase-2024-05-14
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402

from scripts.z1d_live_staging_promotion import (  # noqa: E402
    DEFAULT_DATE_WINDOW_DAYS,
    DEFAULT_HEADLINE_THRESHOLD,
    NON_CLAIM,
    REQUIRED_EXCLUSIONS,
    STAGED_STAGE,
    UNAVAILABLE_TICKERS,
    apply_promotion,
    plan_promotion,
    sha256_file,
)

#: A future live swap is NOT performed by this script -- it is a separate,
#: operator-approved step.  These lines are printed for the operator only.
SWAP_CHECKLIST = (
    "Stop the app / ensure no concurrent writer is bound to live events.db.",
    "Re-hash live events.db and compare it to the recorded source hash.",
    "If unchanged, replace live events.db with the verified working copy (atomic rename).",
    "Verify post-swap counts (events, price_cache, z1a_candidate_pack).",
    "Keep the backup as the rollback restore point.",
)


# ---------------------------------------------------------------------------
# Structural guards (raise) and path derivation
# ---------------------------------------------------------------------------


def _assert_not_live(path: Optional[str], label: str) -> None:
    if path and os.path.realpath(path) == os.path.realpath(db.LIVE_DB_FILE):
        raise ValueError(
            f"refusing to use the live archive as the {label} path ({path}); "
            "this rehearsal never mutates or replaces live"
        )


def _assert_distinct(*paths: Optional[str]) -> None:
    seen: dict[str, str] = {}
    for p in paths:
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp in seen:
            raise ValueError(
                f"refusing: source / backup / working-copy must be three distinct "
                f"paths ({seen[rp]} and {p} resolve to the same file)"
            )
        seen[rp] = p


def _default_paths(source_db: str) -> tuple[str, str]:
    stem = os.path.splitext(os.path.basename(source_db))[0]
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = os.path.join("backups", f"{stem}_z1d_{stamp}.db")
    working = os.path.join("backups", f"{stem}_z1d_{stamp}_working.db")
    return backup, working


# ---------------------------------------------------------------------------
# Read-only counts / integrity helpers
# ---------------------------------------------------------------------------


def _counts(path: str) -> tuple[int, int, int]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        prices = con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        staged = con.execute(
            "SELECT COUNT(*) FROM events WHERE stage=?", (STAGED_STAGE,)).fetchone()[0]
        return events, prices, staged
    finally:
        con.close()


def _integrity_ok(path: str) -> bool:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"
    finally:
        con.close()


def _no_duplicate_candidate_urls(path: str) -> bool:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT source_url, COUNT(*) c FROM event_provenance "
            "WHERE intake_path=? GROUP BY source_url HAVING c > 1", (STAGED_STAGE,)
        ).fetchall()
        return not rows
    finally:
        con.close()


def _denominators_exclude_staged(working_copy_path: str, backup_path: str) -> bool:
    """Staged rows must not enter the coverage loader, and staging must not move
    the track-record denominator at all (membership in NON_THESIS_STAGES). Both
    checks are data-independent, so they hold on a real live clone too."""
    from scripts import event_study_coverage_report as cov
    events, _ = cov._load_events(working_copy_path)
    staged_present = any(e.get("stage") == STAGED_STAGE for e in events)

    orig = db.DB_FILE
    try:
        db.DB_FILE = backup_path
        tr_before = db.compute_track_record()
        db.DB_FILE = working_copy_path
        tr_after = db.compute_track_record()
    finally:
        db.DB_FILE = orig
    unchanged = (
        tr_before.get("total") == tr_after.get("total")
        and tr_before.get("unresolved") == tr_after.get("unresolved")
    )
    return (not staged_present) and unchanged


def _events_suppression(working_copy_path: str) -> dict:
    """Confirm the default ``/events`` listing hides the staged rows and an
    explicit stage query surfaces them -- on the actual built working copy."""
    import api
    import movers_cache
    from fastapi.testclient import TestClient

    orig = db.DB_FILE
    try:
        db.DB_FILE = working_copy_path
        movers_cache.invalidate()
        client = TestClient(api.app)
        default_ids = {e["id"] for e in client.get("/events").json()["items"]}
        staged_ids = {
            e["id"] for e in
            client.get(f"/events?stage={STAGED_STAGE}").json()["items"]
        }
        # Clear caches while still bound to the working copy (a live clone, so
        # the movers_cache table exists) -- never touches the live archive.
        movers_cache.invalidate()
    finally:
        db.DB_FILE = orig
    return {
        "default_hides": bool(staged_ids) and not (default_ids & staged_ids),
        "explicit_surfaces": bool(staged_ids),
    }


# ---------------------------------------------------------------------------
# Working-copy verification
# ---------------------------------------------------------------------------


def verify_working_copy(
    *,
    source_db: str,
    backup_path: str,
    working_copy_path: str,
    source_hash_before: str,
    source_counts_before: tuple[int, int, int],
    apply_env: dict,
) -> dict:
    source_hash_after = sha256_file(source_db)
    source_counts_after = _counts(source_db)
    suppression = _events_suppression(working_copy_path)
    return {
        "source_unchanged_hash": source_hash_after == source_hash_before,
        "source_unchanged_counts": source_counts_after == source_counts_before,
        "source_hash_after": source_hash_after,
        "source_counts_after": source_counts_after,
        "backup_matches_source": (
            os.path.exists(backup_path) and sha256_file(backup_path) == source_hash_before
        ),
        "working_copy_integrity_ok": _integrity_ok(working_copy_path),
        "staged_in_working": _counts(working_copy_path)[2],
        "staged_in_source": source_counts_after[2],
        "required_exclusions_applied": apply_env.get("missing_required_exclusions") == [],
        "no_unexcluded_collisions": apply_env.get("unexcluded_collisions") == [],
        "denominators_exclude_staged": _denominators_exclude_staged(
            working_copy_path, backup_path),
        "events_default_hides_staged": suppression["default_hides"],
        "events_explicit_surfaces_staged": suppression["explicit_surfaces"],
        "no_duplicate_source_url": _no_duplicate_candidate_urls(working_copy_path),
        "x_unavailable_did_not_fail": (
            bool(apply_env.get("write_attempted"))
            and "X" in (apply_env.get("unavailable_tickers") or [])
        ),
    }


def _swap_ready(*, source_counts_before: tuple[int, int, int], apply_env: dict,
                verify: dict) -> bool:
    if apply_env.get("refuse_reason") or apply_env.get("error"):
        return False
    if not apply_env.get("write_attempted"):
        return False
    if verify["staged_in_working"] <= 0:
        return False
    if verify["staged_in_source"] != source_counts_before[2]:
        return False
    flags = (
        "source_unchanged_hash", "source_unchanged_counts", "backup_matches_source",
        "working_copy_integrity_ok", "required_exclusions_applied",
        "no_unexcluded_collisions", "denominators_exclude_staged",
        "events_default_hides_staged", "events_explicit_surfaces_staged",
        "no_duplicate_source_url", "x_unavailable_did_not_fail",
    )
    return all(verify[f] for f in flags)


# ---------------------------------------------------------------------------
# Read-only dry-run planner
# ---------------------------------------------------------------------------


def plan_build(
    *,
    source_db: str,
    candidates_path: str,
    backup_path: Optional[str] = None,
    working_copy_path: Optional[str] = None,
    exclude: tuple = (),
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    headline_threshold: float = DEFAULT_HEADLINE_THRESHOLD,
) -> dict:
    """Read-only plan: derive/echo the backup and working-copy paths and reuse
    the AC1 plan against the source opened ``mode=ro``.  Writes nothing."""
    derived_backup, derived_working = _default_paths(source_db)
    backup = backup_path or derived_backup
    working = working_copy_path or derived_working

    plan = plan_promotion(
        candidates_path=candidates_path, db_path=source_db, exclude=exclude,
        date_window_days=date_window_days, headline_threshold=headline_threshold,
    )
    plan.pop("_to_stage", None)
    return {
        "source_db": source_db,
        "backup_path": backup,
        "working_copy_path": working,
        "ok": plan["ok"],
        "rejected": plan["rejected"],
        "candidate_count": plan["candidate_count"],
        "excluded": plan["excluded"],
        "to_stage_ids": plan["to_stage_ids"],
        "expected_staged_event_count": plan["expected_staged_event_count"],
        "unexcluded_collisions": plan["unexcluded_collisions"],
        "has_unexcluded_collisions": plan["has_unexcluded_collisions"],
        "missing_required_exclusions": plan["missing_required_exclusions"],
        "unavailable_tickers": plan["unavailable_tickers"],
        "non_claim": NON_CLAIM,
    }


# ---------------------------------------------------------------------------
# Gated build orchestration (steps 2-4; never step 5)
# ---------------------------------------------------------------------------


def _new_env(*, source_db, backup_path, working_copy_path) -> dict:
    return {
        "source_db": source_db,
        "backup_path": backup_path,
        "working_copy_path": working_copy_path,
        "refuse_reason": None,
        "confirmed": False,
        "source_hash_before": None,
        "source_hash_after": None,
        "source_counts_before": None,
        "source_counts_after": None,
        "source_unchanged": False,
        "backup_matches_source": False,
        "apply": None,
        "verify": {},
        "swap_ready": False,
        "swap_executed": False,           # this script never swaps live
        "swap_checklist": list(SWAP_CHECKLIST),
        "error": None,
        "non_claim": NON_CLAIM,
    }


def build_staging_copy(
    *,
    source_db: str,
    candidates_path: str,
    backup_path: Optional[str] = None,
    working_copy_path: Optional[str] = None,
    exclude: tuple = (),
    ack_live_staging: bool = False,
    provider: Optional[Any] = None,
    confirm: bool = False,
    max_requests: Optional[int] = None,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    headline_threshold: float = DEFAULT_HEADLINE_THRESHOLD,
) -> dict:
    """Build + verify a promoted working copy from ``source_db`` without ever
    swapping or mutating live.  Hard backstops first (live paths / distinctness),
    then soft gates, then the build, then verification + a swap-ready verdict."""
    # Hard structural backstops -- raise before any rebind or file op.
    _assert_not_live(backup_path, "backup")
    _assert_not_live(working_copy_path, "working copy")
    _assert_distinct(source_db, backup_path, working_copy_path)

    orig_dbfile = db.DB_FILE  # restoration invariant (advisor): always restore
    try:
        return _build_inner(
            source_db=source_db, candidates_path=candidates_path,
            backup_path=backup_path, working_copy_path=working_copy_path,
            exclude=exclude, ack_live_staging=ack_live_staging, provider=provider,
            confirm=confirm, max_requests=max_requests,
            date_window_days=date_window_days, headline_threshold=headline_threshold,
        )
    finally:
        db.DB_FILE = orig_dbfile


def _build_inner(*, source_db, candidates_path, backup_path, working_copy_path,
                 exclude, ack_live_staging, provider, confirm, max_requests,
                 date_window_days, headline_threshold) -> dict:
    env = _new_env(source_db=source_db, backup_path=backup_path,
                   working_copy_path=working_copy_path)

    # Soft flag gates -- no files, no mutation.
    if not ack_live_staging:
        env["refuse_reason"] = "refusing to build without --ack-live-staging"
        return env
    if not backup_path:
        env["refuse_reason"] = "refusing to build without a --backup-path"
        return env
    if not working_copy_path:
        env["refuse_reason"] = "refusing to build without a --working-copy-path"
        return env

    # Early read-only refuse via the AC1 plan -- no files created.
    plan = plan_promotion(
        candidates_path=candidates_path, db_path=source_db, exclude=exclude,
        date_window_days=date_window_days, headline_threshold=headline_threshold,
    )
    plan.pop("_to_stage", None)
    if plan["rejected"]:
        env["refuse_reason"] = "pack failed Z1A validation; refusing to build"
        return env
    if plan["missing_required_exclusions"]:
        env["refuse_reason"] = ("refusing to build: required exclusions missing: "
                                + ", ".join(plan["missing_required_exclusions"]))
        return env
    if plan["has_unexcluded_collisions"]:
        ids = ", ".join(sorted(c["id"] for c in plan["unexcluded_collisions"]))
        env["refuse_reason"] = f"refusing to build: unexcluded collision(s): {ids}"
        return env

    # Backup-clobber gate: never silently replace a non-matching rollback backup.
    if os.path.exists(backup_path) and sha256_file(backup_path) != sha256_file(source_db):
        env["refuse_reason"] = (
            "refusing to build: backup path exists and does not match the source "
            f"({backup_path}); pass a fresh backup path"
        )
        return env

    if not confirm:
        return env  # gates pass, caller did not confirm the build

    # ---- step 2: backup ----
    source_hash_before = sha256_file(source_db)
    source_counts_before = _counts(source_db)
    env["source_hash_before"] = source_hash_before
    env["source_counts_before"] = source_counts_before

    if not (os.path.exists(backup_path) and sha256_file(backup_path) == source_hash_before):
        shutil.copy2(source_db, backup_path)
    if sha256_file(backup_path) != source_hash_before:
        env["error"] = "backup hash does not match source after copy"
        return env

    # ---- step 3: build working copy + AC1 apply (working copy only) ----
    shutil.copy2(backup_path, working_copy_path)
    apply_env = apply_promotion(
        candidates_path=candidates_path, db_path=working_copy_path,
        backup_path=backup_path, ack_live_staging=ack_live_staging,
        exclude=exclude, provider=provider, confirm=True, max_requests=max_requests,
        date_window_days=date_window_days, headline_threshold=headline_threshold,
    )
    env["apply"] = apply_env
    if apply_env.get("refuse_reason") or apply_env.get("error"):
        env["refuse_reason"] = (
            apply_env.get("refuse_reason") or f"apply error: {apply_env.get('error')}")
        return env

    # ---- step 4: verify (source must be byte-identical) ----
    verify = verify_working_copy(
        source_db=source_db, backup_path=backup_path,
        working_copy_path=working_copy_path,
        source_hash_before=source_hash_before,
        source_counts_before=source_counts_before, apply_env=apply_env,
    )
    env["confirmed"] = True
    env["verify"] = verify
    env["source_hash_after"] = verify["source_hash_after"]
    env["source_counts_after"] = verify["source_counts_after"]
    env["source_unchanged"] = (
        verify["source_unchanged_hash"] and verify["source_unchanged_counts"])
    env["backup_matches_source"] = verify["backup_matches_source"]
    env["swap_ready"] = _swap_ready(
        source_counts_before=source_counts_before, apply_env=apply_env, verify=verify)
    return env


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def summarize_plan(plan: dict) -> str:
    L = [
        "Z1D build dry run (READ-ONLY; source opened read-only; nothing written)",
        f"  {plan['non_claim']}",
        "",
        f"  source DB: {plan['source_db']}",
        f"  planned backup path:       {plan['backup_path']}",
        f"  planned working-copy path: {plan['working_copy_path']}",
        f"  pack valid: {plan['ok']} | candidates: {plan['candidate_count']}",
        f"  planned exclusions: {plan['excluded']}",
        f"  expected staged inserts: {plan['expected_staged_event_count']}",
        f"  unavailable ticker(s) (never required): {plan['unavailable_tickers']}",
    ]
    if plan["missing_required_exclusions"]:
        L.append(f"  REQUIRED exclusions still missing: {plan['missing_required_exclusions']}")
    if plan["has_unexcluded_collisions"]:
        L.append("  UNEXCLUDED collisions (build WOULD refuse):")
        for c in plan["unexcluded_collisions"]:
            reasons = sorted({r for col in c["collisions"] for r in col["reasons"]})
            L.append(f"    {c['id']} [{', '.join(reasons)}]")
    else:
        L.append("  no unexcluded collisions")
    L.append("  Dry run only. Building a working copy is a separate, gated step.")
    return "\n".join(L)


def summarize_build(env: dict) -> str:
    if env["refuse_reason"]:
        return f"Z1D build REFUSED: {env['refuse_reason']}\n  (no working copy was built; live untouched.)"
    if env["error"]:
        return f"Z1D build ERROR: {env['error']}\n  (live untouched.)"
    v = env["verify"]
    apply_env = env["apply"] or {}
    m = apply_env.get("measurements") or {}
    L = [
        "Z1D copy-build-then-swap rehearsal (steps 2-4; live is NEVER swapped here)",
        f"  {env['non_claim']}",
        "",
        f"  source DB:    {env['source_db']}",
        f"  backup:       {env['backup_path']}",
        f"  working copy: {env['working_copy_path']}",
        "",
        f"  source unchanged after build: {env['source_unchanged']} "
        f"(hash {(env['source_hash_before'] or '')[:12]}..., staged in source "
        f"{v.get('staged_in_source')})",
        f"  backup matches source: {env['backup_matches_source']}",
        f"  working-copy integrity ok: {v.get('working_copy_integrity_ok')}",
        f"  staged rows in working copy: {v.get('staged_in_working')} "
        f"(events {m.get('events_before')} -> {m.get('events_after')}, "
        f"price_cache +{m.get('price_cache_delta')} additive)",
        f"  required exclusions applied: {v.get('required_exclusions_applied')} | "
        f"no unexcluded collisions: {v.get('no_unexcluded_collisions')}",
        f"  denominators exclude staged: {v.get('denominators_exclude_staged')}",
        f"  default /events hides staged: {v.get('events_default_hides_staged')} | "
        f"explicit stage surfaces them: {v.get('events_explicit_surfaces_staged')}",
        f"  no duplicate candidate source_url: {v.get('no_duplicate_source_url')}",
        f"  X unavailable did not fail build: {v.get('x_unavailable_did_not_fail')}",
        "",
        f"  SWAP-READY VERDICT: {'SWAP-READY' if env['swap_ready'] else 'NOT swap-ready'}",
        "",
        "  Future live swap (NOT EXECUTED by this script; separate operator approval):",
    ]
    for i, step in enumerate(env["swap_checklist"], 1):
        L.append(f"    {i}. {step}")
    L.append("  The live archive was not swapped, not replaced, and not mutated.")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Z1D copy-build-then-swap rehearsal (dry-run default; never swaps live).",
    )
    p.add_argument("--candidates", required=True, help="Z1A candidate-pack YAML.")
    p.add_argument("--source-db", dest="source_db", required=True,
                   help="Source DB (read-only; the live archive is read, never mutated).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                      help="Read-only plan (default).")
    mode.add_argument("--build-copy", dest="dry_run", action="store_false",
                      help="Build + verify a working copy (live is never swapped).")
    p.add_argument("--backup-path", dest="backup_path", default=None)
    p.add_argument("--working-copy-path", dest="working_copy_path", default=None)
    p.add_argument("--ack-live-staging", dest="ack_live_staging", action="store_true")
    p.add_argument("--exclude-candidate", dest="exclude", action="append", default=[])
    p.add_argument("--date-window-days", dest="date_window_days", type=int,
                   default=DEFAULT_DATE_WINDOW_DAYS)
    p.add_argument("--headline-threshold", dest="headline_threshold", type=float,
                   default=DEFAULT_HEADLINE_THRESHOLD)
    p.add_argument("--max-requests", dest="max_requests", type=int, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.dry_run:
        plan = plan_build(
            source_db=args.source_db, candidates_path=args.candidates,
            backup_path=args.backup_path, working_copy_path=args.working_copy_path,
            exclude=tuple(args.exclude),
            date_window_days=args.date_window_days,
            headline_threshold=args.headline_threshold,
        )
        print(json.dumps(plan, indent=2, default=str) if args.json else summarize_plan(plan))
        return 0

    try:
        env = build_staging_copy(
            source_db=args.source_db, candidates_path=args.candidates,
            backup_path=args.backup_path, working_copy_path=args.working_copy_path,
            exclude=tuple(args.exclude), ack_live_staging=args.ack_live_staging,
            provider=None, confirm=True, max_requests=args.max_requests,
            date_window_days=args.date_window_days,
            headline_threshold=args.headline_threshold,
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(env, indent=2, default=str) if args.json else summarize_build(env))
    if env["refuse_reason"] or env["error"] or not env["swap_ready"]:
        return 1
    return 0


__all__ = (
    "plan_build", "build_staging_copy", "verify_working_copy",
    "summarize_plan", "summarize_build", "SWAP_CHECKLIST", "main",
)


if __name__ == "__main__":
    raise SystemExit(main())

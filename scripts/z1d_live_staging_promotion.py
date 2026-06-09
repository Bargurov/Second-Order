#!/usr/bin/env python3
"""AC1 / Z1D-Prep — gated candidate-staging promotion (copy-tested, free-only).

This turns the manual Z1D sequence into one safe, operator-gated workflow:

    backup -> validate pack -> collision report -> explicit exclusions ->
    staged candidate insertion -> free backfill -> SPY densify -> before/after.

It is built entirely from the committed Z1A/Z1B/Z1C parts — the same Z1A
validators, the same collision detector, the same free-only backfill, and the
same targeted SPY densifier — wrapped in a gate so a promotion cannot proceed
unless every safety condition holds.

Two modes:

* DRY RUN (default) is strictly read-only.  It validates the pack, runs the
  collision report, and prints the planned exclusions, the planned staged
  inserts, the expected staged-event count, and any unexcluded collision.  It
  opens the target DB ``mode=ro`` only and refuses to mutate — so a dry run may
  read the live archive without risk.

* APPLY requires the FULL gate set and refuses otherwise:
    - ``--ack-live-staging`` (explicit operator attestation),
    - a FRESH ``--backup-path`` whose sha256 matches the target DB *before* any
      write (a stale or non-matching backup is refused),
    - explicit ``--exclude-candidate`` ids that MUST include the two known
      live duplicates (steel proclamation 9705 -> live event 296; section 301
      -> live event 297),
    - zero *unexcluded* collisions, and a pack that passes the Z1A validators.
  Apply ALSO refuses the live archive outright (an ``_assert_copy_target``
  backstop reused from Z1B): in-place live mutation is impossible in this
  committed script.  Promoting a vetted copy onto the live archive remains a
  separate, future, operator-approved step.

Staged rows land at stage ``z1a_candidate_pack`` (a non-analysis, candidate-only
stage), preserve provenance/source_url, are idempotent by source_url, and all
price_cache writes are additive.  United States Steel (``X``) is delisted; it is
labelled unavailable and is never treated as a required successful ticker.

The backfill is FREE-ONLY by construction (it reuses the Z1B / Z1C free-provider
path) and this module references no paid provider and no paid-confirmation path.
Every output is a descriptive breadth / readiness measurement on a non-promoted
copy — not a directional, predictive, or statistical-importance claim.

Usage::

    # read-only dry run (safe against the live archive)
    python scripts/z1d_live_staging_promotion.py --dry-run \\
        --db events.db \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml

    # apply onto a COPY only (live is refused); all gates required
    python scripts/z1d_live_staging_promotion.py --apply \\
        --db backups/z1d_working_copy.db \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml \\
        --backup-path backups/pre_z1d.db --ack-live-staging \\
        --exclude-candidate section232-steel-proclamation-9705-2018-03-08 \\
        --exclude-candidate section301-china-tariff-increase-2024-05-14
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402

from scripts.z1b_candidate_pack_copy_ingest import (  # noqa: E402
    _assert_copy_target,
    _existing_source_urls,
    _insert_candidate,
    _insert_provenance,
    _load_candidates,
    _now_iso,
    backfill_candidate_prices,
    validate_pack,
    Z1B_STAGE,
)
from scripts.z1b_candidate_collision_report import (  # noqa: E402
    DEFAULT_DATE_WINDOW_DAYS,
    DEFAULT_HEADLINE_THRESHOLD,
    detect_collisions,
)
from scripts.z1b_candidate_pack_report import candidate_readiness  # noqa: E402
from scripts.z1c_spy_gap_densify import densify_spy  # noqa: E402

#: Staged rows reuse the Z1B candidate-pack stage (non-analysis, candidate-only).
STAGED_STAGE = Z1B_STAGE

#: Two candidate ids that the AB1 collision report flagged as live duplicates
#: (steel proclamation 9705 -> live event 296; section 301 -> live event 297).
#: A promotion MUST exclude both — they are required exclusions.
REQUIRED_EXCLUSIONS = frozenset({
    "section232-steel-proclamation-9705-2018-03-08",
    "section301-china-tariff-increase-2024-05-14",
})

#: Tickers that are delisted / not retrievable and must never be treated as a
#: required successful backfill.  United States Steel (X) was acquired and
#: delisted; it is surfaced for the operator but never gates a promotion.
UNAVAILABLE_TICKERS = frozenset({"X"})

NON_CLAIM = (
    "Gated candidate-staging promotion measured on a non-promoted DB copy; "
    "descriptive breadth / readiness only - not a directional, predictive, or "
    "statistical-importance claim. Staged rows are candidate-only stubs, never "
    "analyzed cases."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def sha256_file(path: str) -> str:
    """Streamed sha256 of a file's bytes (the backup-freshness fingerprint)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _all_candidate_tickers(candidates: list[dict]) -> set[str]:
    out: set[str] = set()
    for c in candidates:
        for a in c.get("affected_assets") or []:
            if isinstance(a, dict):
                sym = (a.get("ticker") or "").strip().upper()
                if sym:
                    out.add(sym)
    return out


def _write_filtered_pack(candidates: list[dict]) -> str:
    """Dump the staged candidate subset to a throwaway YAML in the temp dir so
    the reused backfill / densifier only fetch staged tickers (excluded ids,
    including the delisted-X steel candidate, are never fetched)."""
    import yaml
    path = os.path.join(tempfile.gettempdir(), f"z1d_staged_pack_{uuid.uuid4().hex}.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"candidates": candidates}, fh, sort_keys=False, allow_unicode=True)
    return path


# ---------------------------------------------------------------------------
# Read-only planner (the dry run)
# ---------------------------------------------------------------------------


def plan_promotion(
    *,
    candidates_path: str,
    db_path: str,
    exclude: tuple = (),
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    headline_threshold: float = DEFAULT_HEADLINE_THRESHOLD,
) -> dict:
    """Classify the pack against ``db_path`` without mutating anything.

    Returns the planned exclusions, the planned staged inserts, the expected
    staged-event count, the full collision report, the *unexcluded* collisions,
    the required exclusions still missing, and any unavailable ticker.  Opens
    ``db_path`` read-only only — safe against the live archive.
    """
    exclude_set = {str(x) for x in exclude}
    problems = list(validate_pack(candidates_path))
    candidates = _load_candidates(candidates_path)

    report = detect_collisions(
        candidates, db_path,
        date_window_days=date_window_days, headline_threshold=headline_threshold,
    )
    collisions_by_id = {c["id"]: c["collisions"] for c in report["candidates"]}
    unexcluded_collisions = [
        {"id": cid, "collisions": cols}
        for cid, cols in collisions_by_id.items()
        if cols and cid not in exclude_set
    ]

    existing = _existing_source_urls(db_path)
    excluded: list = []
    to_stage: list[dict] = []
    seen_urls: set[str] = set()
    for c in candidates:
        cid = c.get("id")
        if cid in exclude_set:
            excluded.append(cid)
            continue
        url = (c.get("source_url") or "").strip()
        if url and (url in existing or url in seen_urls):
            continue  # idempotent: already present, or a duplicate within the pack
        if url:
            seen_urls.add(url)
        to_stage.append(c)

    missing_required = sorted(rid for rid in REQUIRED_EXCLUSIONS if rid not in exclude_set)
    unavailable = sorted(_all_candidate_tickers(candidates) & UNAVAILABLE_TICKERS)

    return {
        "ok": not problems,
        "rejected": problems,
        "candidate_count": len(candidates),
        "excluded": excluded,
        "to_stage_ids": [c.get("id") for c in to_stage],
        "expected_staged_event_count": len(to_stage),
        "collisions": report,
        "unexcluded_collisions": unexcluded_collisions,
        "has_unexcluded_collisions": bool(unexcluded_collisions),
        "missing_required_exclusions": missing_required,
        "unavailable_tickers": unavailable,
        "non_claim": NON_CLAIM,
        "_to_stage": to_stage,
    }


# ---------------------------------------------------------------------------
# Apply-mode gate
# ---------------------------------------------------------------------------


def _refuse_reason(
    *, plan: dict, backup_path: Optional[str], ack_live_staging: bool, db_path: str,
) -> Optional[str]:
    """Return a refusal string when any apply gate fails, else ``None``.

    Order is intentional: validation, then operator attestation, then the
    backup-freshness gate, then the required-exclusion and collision gates.
    """
    if plan["rejected"]:
        return "pack failed Z1A validation; refusing to stage"
    if not ack_live_staging:
        return "refusing to apply without --ack-live-staging (explicit operator attestation)"
    if not backup_path:
        return "refusing to apply without a --backup-path"
    if not os.path.exists(backup_path):
        return f"refusing to apply: backup path does not exist ({backup_path})"
    if sha256_file(backup_path) != sha256_file(db_path):
        return "refusing to apply: backup is stale (sha256 does not match the target DB)"
    if plan["missing_required_exclusions"]:
        return ("refusing to apply: required exclusions missing: "
                + ", ".join(plan["missing_required_exclusions"]))
    if plan["has_unexcluded_collisions"]:
        ids = ", ".join(sorted(c["id"] for c in plan["unexcluded_collisions"]))
        return f"refusing to apply: unexcluded collision(s): {ids}"
    return None


# ---------------------------------------------------------------------------
# Measurement (read-only counts + reused candidate readiness)
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


def _measure(*, backup_path: str, db_path: str, readiness_pack: str) -> dict:
    eb, pb, sb = _counts(backup_path)
    ea, pa, sa = _counts(db_path)
    readiness = candidate_readiness(db_path, readiness_pack)
    return {
        "events_before": eb, "events_after": ea, "events_delta": ea - eb,
        "price_cache_before": pb, "price_cache_after": pa, "price_cache_delta": pa - pb,
        "staged_before": sb, "staged_after": sa, "staged_delta": sa - sb,
        "candidate_readiness": readiness,
        "candidate_ready_count": sum(1 for r in readiness if r.get("any_available")),
    }


# ---------------------------------------------------------------------------
# Gated apply
# ---------------------------------------------------------------------------


def apply_promotion(
    *,
    candidates_path: str,
    db_path: str,
    backup_path: Optional[str] = None,
    ack_live_staging: bool = False,
    exclude: tuple = (),
    provider: Optional[Any] = None,
    confirm: bool = False,
    max_requests: Optional[int] = None,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    headline_threshold: float = DEFAULT_HEADLINE_THRESHOLD,
) -> dict:
    """Stage the non-excluded candidates into ``db_path`` when every gate holds.

    Hard backstop first: ``_assert_copy_target`` refuses the live archive
    outright (raises ``ValueError``), so this function can never mutate live.
    Then the soft gates (validation, attestation, fresh backup, required
    exclusions, zero unexcluded collisions) each return a ``refuse_reason`` with
    no writes.  On success it stages rows, backfills prices (free provider),
    densifies SPY, and returns a before/after measurement.  Idempotent by
    source_url; additive price writes only.
    """
    # Hard backstop — in-place live mutation is impossible in this script.
    _assert_copy_target(db_path)

    plan = plan_promotion(
        candidates_path=candidates_path, db_path=db_path, exclude=exclude,
        date_window_days=date_window_days, headline_threshold=headline_threshold,
    )
    to_stage = plan.pop("_to_stage", [])

    env: dict[str, Any] = {
        "ok": plan["ok"],
        "refuse_reason": None,
        "write_attempted": False,
        "inserted_count": 0,
        "inserted": [],
        "excluded": plan["excluded"],
        "expected_staged_event_count": plan["expected_staged_event_count"],
        "unexcluded_collisions": plan["unexcluded_collisions"],
        "missing_required_exclusions": plan["missing_required_exclusions"],
        "unavailable_tickers": plan["unavailable_tickers"],
        "staged_stage": STAGED_STAGE,
        "non_analysis_member": STAGED_STAGE in db.NON_ANALYSIS_STAGES,
        "measurements": {},
        "error": None,
        "non_claim": NON_CLAIM,
    }

    refuse = _refuse_reason(
        plan=plan, backup_path=backup_path,
        ack_live_staging=ack_live_staging, db_path=db_path,
    )
    if refuse is not None:
        env["refuse_reason"] = refuse
        return env

    if not confirm:
        return env  # gates pass, but the caller did not confirm the write
    if not to_stage:
        return env  # idempotent no-op — nothing new to stage

    created_at = _now_iso()
    orig = db.DB_FILE
    try:
        db.DB_FILE = db_path
        db.init_db()
    finally:
        db.DB_FILE = orig

    inserted: list[dict] = []
    con = sqlite3.connect(db_path, isolation_level=None, timeout=30.0)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            for c in to_stage:
                eid = _insert_candidate(con, c, created_at=created_at)
                _insert_provenance(con, eid, c, created_at=created_at)
                inserted.append({
                    "event_id": eid, "id": c.get("id"),
                    "source_url": (c.get("source_url") or "").strip(),
                })
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    except Exception as exc:  # noqa: BLE001
        env["error"] = f"{type(exc).__name__}: {exc}"
        return env
    finally:
        con.close()

    env["write_attempted"] = True
    env["inserted"] = inserted
    env["inserted_count"] = len(inserted)

    # Free-only additive backfill + targeted SPY densify on the staged subset.
    filtered = _write_filtered_pack(to_stage)
    try:
        backfill_candidate_prices(
            copy_path=db_path, candidates_path=filtered,
            provider=provider, max_requests=max_requests,
        )
        densify_spy(
            copy_path=db_path, candidates_path=filtered,
            provider=provider, max_requests=max_requests,
        )
        env["measurements"] = _measure(
            backup_path=backup_path, db_path=db_path, readiness_pack=filtered,
        )
    finally:
        try:
            os.remove(filtered)
        except OSError:
            pass

    return env


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def summarize_plan(plan: dict) -> str:
    L = [
        "Z1D dry run (READ-ONLY; nothing written; live archive is opened read-only)",
        f"  {plan['non_claim']}",
        "",
        f"  pack valid: {plan['ok']}"
        + ("" if plan["ok"] else f"  rejected: {plan['rejected']}"),
        f"  candidates: {plan['candidate_count']} | planned exclusions: {plan['excluded']}",
        f"  planned staged inserts ({plan['expected_staged_event_count']}): {plan['to_stage_ids']}",
        f"  unavailable ticker(s) (never required): {plan['unavailable_tickers']}",
    ]
    if plan["missing_required_exclusions"]:
        L.append(f"  REQUIRED exclusions still missing: {plan['missing_required_exclusions']}")
    if plan["has_unexcluded_collisions"]:
        L.append("  UNEXCLUDED collisions (apply WOULD refuse):")
        for c in plan["unexcluded_collisions"]:
            reasons = sorted({r for col in c["collisions"] for r in col["reasons"]})
            L.append(f"    {c['id']} [{', '.join(reasons)}]")
    else:
        L.append("  no unexcluded collisions")
    L.append("  Dry run only. Apply is a separate, fully gated, operator step.")
    return "\n".join(L)


def summarize_apply(env: dict) -> str:
    if env["refuse_reason"]:
        return f"Z1D apply REFUSED: {env['refuse_reason']}\n  (nothing was written.)"
    m = env.get("measurements") or {}
    L = [
        "Z1D apply (COPY ONLY; live archive is refused by this script)",
        f"  {env['non_claim']}",
        f"  staged rows inserted: {env['inserted_count']} at stage {env['staged_stage']} "
        f"(non-analysis: {env['non_analysis_member']})",
        f"  excluded: {env['excluded']}",
        f"  unavailable ticker(s) (never required): {env['unavailable_tickers']}",
    ]
    if m:
        L += [
            f"  events: {m['events_before']} -> {m['events_after']} ({m['events_delta']:+d})",
            f"  price_cache: {m['price_cache_before']} -> {m['price_cache_after']} "
            f"({m['price_cache_delta']:+d}, additive)",
            f"  candidate readiness: {m['candidate_ready_count']}/"
            f"{len(m['candidate_readiness'])} have >=1 event-study-available ticker",
        ]
    L.append("  Copy-only result. Promoting a vetted copy onto live is a separate operator step.")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Gated Z1D candidate-staging promotion (dry-run default; apply is copy-only).",
    )
    p.add_argument("--candidates", required=True, help="Z1A candidate-pack YAML.")
    p.add_argument("--db", dest="db_path", required=True,
                   help="Target DB. Dry run reads it read-only; apply refuses the live archive.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                      help="Read-only plan (default).")
    mode.add_argument("--apply", dest="dry_run", action="store_false",
                      help="Stage onto a COPY (live refused); requires the full gate set.")
    p.add_argument("--backup-path", dest="backup_path", default=None,
                   help="Fresh backup whose sha256 must match the target DB before any write.")
    p.add_argument("--ack-live-staging", dest="ack_live_staging", action="store_true",
                   help="Explicit operator attestation required for apply.")
    p.add_argument("--exclude-candidate", dest="exclude", action="append", default=[],
                   help="Candidate id to exclude (repeatable). Must include the required duplicates.")
    p.add_argument("--date-window-days", dest="date_window_days", type=int,
                   default=DEFAULT_DATE_WINDOW_DAYS)
    p.add_argument("--headline-threshold", dest="headline_threshold", type=float,
                   default=DEFAULT_HEADLINE_THRESHOLD)
    p.add_argument("--max-requests", dest="max_requests", type=int, default=None)
    p.add_argument("--json", action="store_true", help="Emit the full JSON result.")
    args = p.parse_args(argv)

    if args.dry_run:
        plan = plan_promotion(
            candidates_path=args.candidates, db_path=args.db_path,
            exclude=tuple(args.exclude),
            date_window_days=args.date_window_days,
            headline_threshold=args.headline_threshold,
        )
        public = {k: v for k, v in plan.items() if not k.startswith("_")}
        print(json.dumps(public, indent=2, default=str) if args.json else summarize_plan(plan))
        return 0

    # Apply path — the free provider is used inside the reused backfill/densify.
    try:
        env = apply_promotion(
            candidates_path=args.candidates, db_path=args.db_path,
            backup_path=args.backup_path, ack_live_staging=args.ack_live_staging,
            exclude=tuple(args.exclude), provider=None, confirm=True,
            max_requests=args.max_requests,
            date_window_days=args.date_window_days,
            headline_threshold=args.headline_threshold,
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(env, indent=2, default=str) if args.json else summarize_apply(env))
    if env["refuse_reason"] or env["error"]:
        return 1
    return 0


__all__ = (
    "REQUIRED_EXCLUSIONS", "UNAVAILABLE_TICKERS", "STAGED_STAGE", "NON_CLAIM",
    "sha256_file", "plan_promotion", "apply_promotion",
    "summarize_plan", "summarize_apply", "main",
)


if __name__ == "__main__":
    raise SystemExit(main())

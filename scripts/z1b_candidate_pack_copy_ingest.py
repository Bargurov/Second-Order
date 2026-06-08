#!/usr/bin/env python3
"""Z1B (Gate 1) — copy-only ingestion + FREE price backfill for the Z1A pack.

Ingests a Z1A candidate pack (``data/candidates/*.yaml``) into a COPY of the
archive (``events`` + ``event_provenance``) and backfills daily closes for the
candidate tickers into that copy's ``price_cache`` using the FREE yfinance
provider only.  Everything here is gated to a DB copy:

* It REFUSES to target the live archive (``db.LIVE_DB_FILE``) and REQUIRES an
  explicit copy path — ingestion and backfill both raise on a live target.
* It REUSES the Z1A validators (structural/anti-synthetic + banned-framing) and
  refuses a pack that fails either — it never weakens or re-implements them.
* Each candidate becomes ONE ``events`` row (stage ``z1a_candidate_pack``,
  ``market_tickers`` = minimal ``[{symbol, role}]`` with roles VERBATIM — no
  directional reframing, no precomputed verdict) plus ONE ``event_provenance``
  row that preserves ``source_url`` and marks ``intake_path``.  Idempotent by
  ``event_provenance.source_url``.
* The backfill is FREE-ONLY by construction: it pins the free yfinance provider,
  refuses any non-free provider, and never makes a billed call.

It never promotes the copy to live (that is the separate, operator-approved
Gate 2), never edits UI/docs, and makes no directional / significance claim.

Usage::

    # dry-run plan (read-only)
    python scripts/z1b_candidate_pack_copy_ingest.py \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml \\
        --copy-path backups/z1b_working_copy.db

    # ingest into the copy, then backfill its prices (free provider)
    python scripts/z1b_candidate_pack_copy_ingest.py \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml \\
        --copy-path backups/z1b_working_copy.db --write --backfill
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402

# Inert, distinct markers: a Z1B copy row is clearly a candidate-pack origin and
# is never mistaken for an analysed live event.  The intake_path is the durable
# provenance marker; the stage keeps the row out of any membership-based
# non-analysis filter while staying measurable on the copy.
Z1B_STAGE = "z1a_candidate_pack"
Z1B_PERSISTENCE = "unscored"
Z1B_INTAKE_PATH = "z1a_candidate_pack"
Z1B_MECH_LABEL_PROV = "curated"
Z1B_ORIGIN_NOTE = (
    "z1a_candidate_pack origin; candidate_only_not_ingested; copy-only measurement"
)

#: The only provider this module will use — the free yfinance adapter.
_FREE_PROVIDER_NAME = "yfinance"

DEFAULT_DAYS_BEFORE = 400
DEFAULT_DAYS_AFTER = 120


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _load_candidates(path: str) -> list[dict]:
    import yaml
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict) and "candidates" in data:
        return list(data["candidates"] or [])
    if isinstance(data, list):
        return list(data)
    return []


def validate_pack(candidates_path: str) -> list[str]:
    """Combined Z1A validation: structural/anti-synthetic + banned-framing.

    Reuses the committed Z1A validators verbatim — a non-empty return means the
    pack must not be ingested.
    """
    from scripts.validate_no_synthetic_data import validate_candidates
    from scripts.validate_event_content_framing import scan_candidates
    return list(validate_candidates(candidates_path)) + list(scan_candidates(candidates_path))


def _assert_copy_target(copy_path: Optional[str]) -> None:
    """Raise unless ``copy_path`` is an explicit path that is NOT the live archive."""
    if not copy_path:
        raise ValueError(
            "an explicit copy_path is required; refusing to default to the live archive"
        )
    if os.path.realpath(copy_path) == os.path.realpath(db.LIVE_DB_FILE):
        raise ValueError(
            f"refusing to target the live archive ({copy_path}); pass a DB copy"
        )


def _market_tickers_json(candidate: dict) -> str:
    """Minimal ``[{symbol, role}]`` JSON — roles verbatim, no verdict fields."""
    out = []
    for a in candidate.get("affected_assets") or []:
        if not isinstance(a, dict):
            continue
        sym = (a.get("ticker") or "").strip().upper()
        role = (a.get("role") or "").strip()
        if sym and role:
            out.append({"symbol": sym, "role": role})
    return json.dumps(out)


def _existing_source_urls(copy_path: str) -> set[str]:
    if not copy_path or not os.path.exists(copy_path):
        return set()
    try:
        con = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return set()
    try:
        rows = con.execute(
            "SELECT source_url FROM event_provenance "
            "WHERE source_url IS NOT NULL AND TRIM(source_url) != ''"
        ).fetchall()
        return {r[0] for r in rows if r[0]}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Dry-run planner — read-only
# ---------------------------------------------------------------------------


def plan_copy_ingest(*, candidates_path: str, copy_path: str) -> dict:
    """Classify candidates into insert / skip(existing) / reject.  Read-only."""
    _assert_copy_target(copy_path)
    problems = validate_pack(candidates_path)
    candidates = _load_candidates(candidates_path)
    existing = _existing_source_urls(copy_path)

    insert: list[dict] = []
    to_insert: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for c in candidates:
        url = (c.get("source_url") or "").strip()
        if url in existing or url in seen:
            skipped.append({"id": c.get("id"), "source_url": url,
                            "reason": "source_url already present"})
            continue
        seen.add(url)
        insert.append(c)
        to_insert.append({"id": c.get("id"), "source_url": url,
                          "mechanism_family": c.get("mechanism_family")})

    return {
        "ok": not problems,
        "rejected": list(problems),
        "candidate_count": len(candidates),
        "to_insert": to_insert,
        "to_insert_count": len(to_insert),
        "skipped_existing": skipped,
        "_insert_candidates": insert,
    }


# ---------------------------------------------------------------------------
# Guarded copy writer
# ---------------------------------------------------------------------------


def _insert_candidate(con: sqlite3.Connection, c: dict, *, created_at: str) -> int:
    cur = con.execute(
        "INSERT INTO events (timestamp, headline, stage, persistence, event_date, "
        "mechanism_family, mechanism_summary, market_tickers, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            created_at,
            (c.get("title") or "").strip(),
            Z1B_STAGE,
            Z1B_PERSISTENCE,
            (str(c.get("event_date") or "")[:10]),
            (c.get("mechanism_family") or "none").strip(),
            (c.get("mechanism_summary") or "").strip() or None,
            _market_tickers_json(c),
            Z1B_ORIGIN_NOTE,
        ),
    )
    return int(cur.lastrowid)


def _insert_provenance(con: sqlite3.Connection, event_id: int, c: dict, *, created_at: str) -> None:
    con.execute(
        "INSERT INTO event_provenance (event_id, source_type, source_publisher, source_url, "
        "source_published_at, mechanism_label_provenance, intake_path, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            event_id,
            (c.get("source_type") or "other_primary").strip(),
            None,
            (c.get("source_url") or "").strip(),
            (str(c.get("event_date") or "")[:10]) or None,
            Z1B_MECH_LABEL_PROV,
            Z1B_INTAKE_PATH,
            created_at,
        ),
    )


def apply_copy_ingest(*, candidates_path: str, copy_path: str, confirm: bool = False) -> dict:
    """Ingest the pack into ``copy_path`` (events + event_provenance) when every
    gate passes.  Refuses a live target; idempotent by source_url; all-or-nothing.
    """
    _assert_copy_target(copy_path)
    plan = plan_copy_ingest(candidates_path=candidates_path, copy_path=copy_path)
    insert = plan.pop("_insert_candidates", [])
    env = {**plan, "write_attempted": False, "inserted_count": 0, "inserted": [],
           "refuse_reason": None, "error": None}

    if not confirm:
        return env
    if plan["rejected"]:
        env["refuse_reason"] = "refusing to write: pack failed Z1A validation"
        return env
    if not insert:
        return env  # idempotent no-op

    created_at = _now_iso()
    # Ensure the schema exists on the copy, then insert in one transaction.
    orig = db.DB_FILE
    inserted: list[dict] = []
    try:
        db.DB_FILE = copy_path
        db.init_db()
    finally:
        db.DB_FILE = orig

    con = sqlite3.connect(copy_path, isolation_level=None, timeout=30.0)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            for c in insert:
                eid = _insert_candidate(con, c, created_at=created_at)
                _insert_provenance(con, eid, c, created_at=created_at)
                inserted.append({"event_id": eid, "source_url": (c.get("source_url") or "").strip()})
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
    return env


# ---------------------------------------------------------------------------
# Free-only price backfill into the copy
# ---------------------------------------------------------------------------


def _candidate_windows(candidates_path: str, *, days_before: int, days_after: int) -> list[dict]:
    """One ``{symbol, start, end}`` window per ticker (+ SPY), wide enough that a
    non-event placebo anchor with a full 60+20 window CAN exist (so any
    placebo-feasibility change is real, not a window artifact)."""
    candidates = _load_candidates(candidates_path)
    spans: dict[str, list[str]] = {}
    all_dates: list[str] = []
    for c in candidates:
        ed = str(c.get("event_date") or "")[:10]
        if not ed:
            continue
        all_dates.append(ed)
        for a in c.get("affected_assets") or []:
            if not isinstance(a, dict):
                continue
            sym = (a.get("ticker") or "").strip().upper()
            if sym:
                spans.setdefault(sym, []).append(ed)
    if all_dates:
        spans["SPY"] = sorted(all_dates)  # benchmark spans the whole pack

    def _win(dates: list[str]) -> tuple[str, str]:
        lo = min(dates)
        hi = max(dates)
        start = (_dt.date.fromisoformat(lo) - _dt.timedelta(days=days_before)).isoformat()
        end = (_dt.date.fromisoformat(hi) + _dt.timedelta(days=days_after)).isoformat()
        return start, end

    out = []
    for sym in sorted(spans):
        start, end = _win(spans[sym])
        out.append({"symbol": sym, "start": start, "end": end})
    return out


def backfill_candidate_prices(
    *,
    copy_path: str,
    candidates_path: str,
    provider: Optional[Any] = None,
    max_requests: Optional[int] = None,
    days_before: int = DEFAULT_DAYS_BEFORE,
    days_after: int = DEFAULT_DAYS_AFTER,
    auto_adjust_flags: tuple = (False, True),
) -> dict:
    """Backfill candidate-ticker daily closes into ``copy_path`` with the FREE
    provider only.  Refuses a live target and any non-free provider; never
    promotes; never makes a billed call.
    """
    _assert_copy_target(copy_path)
    if not os.path.exists(copy_path):
        raise FileNotFoundError(copy_path)

    import market_data
    import price_cache

    prov = provider if provider is not None else market_data.YFinanceProvider()
    if getattr(prov, "provider_name", None) != _FREE_PROVIDER_NAME:
        raise ValueError(
            "refusing a non-free provider; this backfill uses the free yfinance "
            f"adapter only (got provider_name={getattr(prov, 'provider_name', None)!r})"
        )

    windows = _candidate_windows(candidates_path, days_before=days_before, days_after=days_after)

    def _count(path: str) -> int:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        finally:
            con.close()

    rows_before = _count(copy_path)
    summary: dict[str, Any] = {
        "symbols": 0, "requests": 0, "failures": [], "unavailable": [],
        "rows_before": rows_before, "rows_after": rows_before, "rows_written": 0,
        "windows": windows,
    }

    orig_db = db.DB_FILE
    orig_prov = market_data.get_provider()
    try:
        db.DB_FILE = copy_path
        market_data.set_provider(prov)
        for w in windows:
            if max_requests is not None and summary["requests"] >= max_requests:
                break
            sym, start, end = w["symbol"], w["start"], w["end"]
            summary["symbols"] += 1
            got_any = False
            for flag in auto_adjust_flags:
                if max_requests is not None and summary["requests"] >= max_requests:
                    break
                summary["requests"] += 1
                try:
                    res = price_cache.fetch_daily_cached(sym, start=start, end=end, auto_adjust=flag)
                    if res is not None and len(res):
                        got_any = True
                except Exception as exc:  # provider/DB errors must not abort the run
                    summary["failures"].append({"symbol": sym, "flag": flag, "error": str(exc)})
            if not got_any:
                summary["unavailable"].append(sym)
    finally:
        db.DB_FILE = orig_db
        market_data.set_provider(orig_prov)

    summary["rows_after"] = _count(copy_path)
    summary["rows_written"] = summary["rows_after"] - rows_before
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Z1B Gate-1 copy-only ingestion + free backfill for a Z1A candidate pack."
    )
    p.add_argument("--candidates", required=True)
    p.add_argument("--copy-path", dest="copy_path", required=True,
                   help="DB copy to mutate (must NOT be the live archive).")
    p.add_argument("--write", action="store_true", help="Ingest into the copy.")
    p.add_argument("--backfill", action="store_true", help="Backfill prices (free provider) after ingest.")
    p.add_argument("--max-requests", dest="max_requests", type=int, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        _assert_copy_target(args.copy_path)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    out: dict[str, Any] = {}
    if not args.write:
        out["plan"] = {k: v for k, v in
                       plan_copy_ingest(candidates_path=args.candidates,
                                        copy_path=args.copy_path).items()
                       if not k.startswith("_")}
    else:
        out["ingest"] = apply_copy_ingest(candidates_path=args.candidates,
                                          copy_path=args.copy_path, confirm=True)
        if args.backfill and out["ingest"].get("rejected"):
            out["backfill"] = {"skipped": "pack rejected; no backfill"}
        elif args.backfill:
            out["backfill"] = backfill_candidate_prices(
                copy_path=args.copy_path, candidates_path=args.candidates,
                max_requests=args.max_requests)

    print(json.dumps(out, indent=2, default=str) if args.json else out)
    if out.get("ingest", {}).get("error") or (not out.get("ingest", {"write_attempted": True}).get("write_attempted", True) and args.write):
        return 1
    return 0


__all__ = (
    "validate_pack", "plan_copy_ingest", "apply_copy_ingest",
    "backfill_candidate_prices", "Z1B_STAGE", "Z1B_INTAKE_PATH", "main",
)


if __name__ == "__main__":
    raise SystemExit(main())

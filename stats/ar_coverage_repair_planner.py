"""V2A — read-only, DRY-RUN planner for exposed-name AR coverage repair.

Reproduces the current single-event AR coverage snapshot and enumerates the
MISSING exposed/loser (and beneficiary) AR units, classifies each by
fixability, and proposes bounded per-symbol/date windows that a FUTURE,
operator-gated DB-copy backfill (V2B) could fetch.

Zero-cost / read-only by construction:
  * the SOURCE archive is opened ``mode=ro`` for cache presence + event rows;
  * the existing read-only event-study engine is run against a TEMP COPY of
    the source (``db.DB_FILE`` is rebound for the duration, then restored) so
    the live archive is never written;
  * there is NO writer, NO provider import, NO network/paid call, NO cache
    mutation, and NO file output.

This planner improves *coverage / representativeness* of the descriptive
event-window reads only.  It makes no statistical-significance or edge claim
and changes no research conclusion: a single-event AR stays an ``n = 1``
descriptive point estimate.  The actual provider fetch + cache write is the
separate V2B step, which requires a DB copy and an explicit operator
``confirm_paid`` gate (never exercised here).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import date, timedelta
from typing import Any, Optional

import db as _db
from event_study_validation import (
    BENCHMARK_TICKER,
    ESTIMATION_WINDOW,
    HORIZONS,
    STATUS_AVAILABLE,
    build_event_study_validation,
    event_study_ar_for_symbol,
)

try:
    from family_inference import resolve_effective_family
except Exception:  # pragma: no cover - family is best-effort only
    def resolve_effective_family(_event: Any) -> str:
        return "none"


# Fixability classes ---------------------------------------------------------
ALIAS = "alias_manual_review"        # symbol carries a "(proxy)" suffix
FUTURE = "future_not_yet"            # +20 business days not yet elapsed
NO_CACHE = "no_cache_backfill"       # zero cached rows for the symbol
BACKFILL_EARLIER = "backfill_earlier"   # <60 pre-event bars; fetch earlier history
BACKFILL_FORWARD = "backfill_forward"   # forward bars missing; extend to today
GAP = "gap_fill_maybe"               # contiguity hole inside the window
DELISTED = "delisted_stale"          # cache ends before the event (likely gone)
OTHER = "other"

FIXABLE_CLASSES = frozenset({NO_CACHE, BACKFILL_EARLIER, BACKFILL_FORWARD, GAP})

# The T8 representative slate (minimal scenario).
CASE_LIBRARY_IDS = [105, 29, 85, 215, 72, 84, 94, 80, 1, 240, 238, 300, 211, 239, 214]

SCENARIOS = ("caselib", "scored", "saved")

DISCLAIMER = (
    "Planner output is a coverage / representativeness preview only. Filling "
    "exposed-name AR makes the descriptive event-window reads less thin on the "
    "exposed side; it is NOT statistical significance, NOT an edge, and NOT a "
    "research-conclusion change. Single-event AR stays an n = 1 descriptive "
    "point estimate. Provider fetch + cache write is the separate, gated V2B "
    "step (DB copy + explicit operator confirm_paid)."
)

# Pre-event room (~3 trading months) + forward room for the backfill window.
_PRE_EVENT_CAL_DAYS = 95
_POST_EVENT_CAL_DAYS = 30
# Rough business-day count inside a proposed window (for an approximate row est).
_APPROX_BARS_PER_WINDOW = 90


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _business_day_offset(start: date, n: int) -> date:
    if n <= 0:
        return start
    out, remaining = start, n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _parse(d: Any) -> Optional[date]:
    if not isinstance(d, str) or not d:
        return None
    try:
        return date.fromisoformat(d[:10])
    except ValueError:
        return None


def classify_missing(
    symbol: str,
    event_date: str,
    blocking_reasons: list[str],
    cache: Optional[tuple[str, str]],
    today: date,
) -> str:
    """Bucket one missing AR unit. ``cache`` is ``(first_iso, last_iso)`` or None.

    Order matters: alias and future-bar take precedence (neither is a backfill
    problem), then no-cache, then delisted (cache ends before the event), then
    the reason-driven backfill buckets.
    """
    if "(proxy)" in (symbol or "").lower():
        return ALIAS
    edt = _parse(event_date)
    if edt is not None and _business_day_offset(edt, max(HORIZONS)) > today:
        return FUTURE
    if not cache:
        return NO_CACHE
    first, last = cache
    if edt is not None and last[:10] < edt.isoformat():
        return DELISTED
    reasons = blocking_reasons or []
    if any("insufficient_estimation_window_primary" in r for r in reasons):
        return BACKFILL_EARLIER
    if any("missing_forward_cache" in r for r in reasons):
        return BACKFILL_FORWARD
    if any("no_contiguous" in r for r in reasons):
        return GAP
    return OTHER


def proposed_window(event_date: str) -> tuple[str, str]:
    """A bounded ``(start_iso, end_iso)`` daily-close window around the event."""
    edt = _parse(event_date)
    if edt is None:
        return ("", "")
    return (
        (edt - timedelta(days=_PRE_EVENT_CAL_DAYS)).isoformat(),
        (edt + timedelta(days=_POST_EVENT_CAL_DAYS)).isoformat(),
    )


# ---------------------------------------------------------------------------
# Read-only DB access
# ---------------------------------------------------------------------------

def _ro(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _cache_presence(con: sqlite3.Connection) -> dict[str, tuple[int, str, str]]:
    out: dict[str, tuple[int, str, str]] = {}
    for r in con.execute(
        "SELECT ticker, COUNT(*) n, MIN(date) lo, MAX(date) hi FROM price_cache GROUP BY ticker"
    ):
        out[(r["ticker"] or "").upper()] = (r["n"], r["lo"], r["hi"])
    return out


def _events_for_scenario(con: sqlite3.Connection, scenario: str) -> list[dict]:
    import json
    rows = []
    for r in con.execute("SELECT * FROM events"):
        d = dict(r)
        mt = d.get("market_tickers")
        if isinstance(mt, str) and mt:
            try:
                d["market_tickers"] = json.loads(mt)
            except ValueError:
                d["market_tickers"] = []
        tc = d.get("transmission_chain")
        if isinstance(tc, str) and tc:
            try:
                d["transmission_chain"] = json.loads(tc)
            except ValueError:
                pass
        rows.append(d)
    scored = [d for d in rows if isinstance(d.get("market_tickers"), list) and d["market_tickers"]]
    if scenario == "caselib":
        ids = set(CASE_LIBRARY_IDS)
        return [d for d in scored if d.get("id") in ids]
    if scenario == "saved":
        return rows
    return scored  # "scored"


def _dedup_role_units(event: dict) -> list[tuple[str, str]]:
    """``(symbol, role)`` for each first-seen beneficiary/loser ticker."""
    out, seen = [], set()
    for t in event.get("market_tickers") or []:
        if not isinstance(t, dict):
            continue
        role = (t.get("role") or "").lower()
        sym = (t.get("symbol") or "").strip()
        if role not in ("beneficiary", "loser") or not sym:
            continue
        key = sym.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append((sym, role))
    return out


# ---------------------------------------------------------------------------
# Public planner
# ---------------------------------------------------------------------------

def build_repair_plan(db_path: str, scenario: str = "scored", today: Optional[date] = None) -> dict:
    """Return a read-only, dry-run repair plan for ``db_path``.

    Runs the real event-study engine against a TEMP COPY so the source archive
    is never written. ``today`` defaults to the real date (override in tests).
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    if today is None:
        today = date.today()

    con = _ro(db_path)
    try:
        cache = _cache_presence(con)
        events = _events_for_scenario(con, scenario)
    finally:
        con.close()

    # Run the engine against a throwaway copy; never touch the source path.
    tmpdir = tempfile.mkdtemp(prefix="arcov_plan_")
    copy = os.path.join(tmpdir, "copy.db")
    shutil.copy(db_path, copy)
    original_db_file = _db.DB_FILE
    snapshot = {r: {"covered": 0, "total": 0} for r in ("beneficiary", "loser")}
    missing: list[dict] = []
    try:
        _db.DB_FILE = copy
        for ev in events:
            ed = ev.get("event_date")
            fam = "none"
            try:
                fam = resolve_effective_family(ev)
            except Exception:
                fam = "none"
            primary_ar = build_event_study_validation(ev).get("status") == STATUS_AVAILABLE
            for sym, role in _dedup_role_units(ev):
                res = event_study_ar_for_symbol(sym, ed)
                covered = res.get("status") == STATUS_AVAILABLE
                snapshot[role]["total"] += 1
                if covered:
                    snapshot[role]["covered"] += 1
                    continue
                c = cache.get(sym.strip().upper())
                cls = classify_missing(
                    sym, ed, res.get("blocking_reasons") or [],
                    (c[1], c[2]) if c else None, today,
                )
                start, end = proposed_window(ed) if cls in FIXABLE_CLASSES else ("", "")
                missing.append({
                    "event_id": ev.get("id"),
                    "event_date": ed,
                    "symbol": sym,
                    "role": role,
                    "family": fam,
                    "primary_ar_exists": primary_ar,
                    "cache_rows": c[0] if c else 0,
                    "cache_first": c[1] if c else None,
                    "cache_last": c[2] if c else None,
                    "blocking_reasons": res.get("blocking_reasons") or [],
                    "fixability_class": cls,
                    "window_start": start,
                    "window_end": end,
                })
    finally:
        _db.DB_FILE = original_db_file
        shutil.rmtree(tmpdir, ignore_errors=True)

    snapshot["total"] = {
        "covered": snapshot["beneficiary"]["covered"] + snapshot["loser"]["covered"],
        "total": snapshot["beneficiary"]["total"] + snapshot["loser"]["total"],
    }

    by_role: dict[str, int] = {"beneficiary": 0, "loser": 0}
    by_class: dict[str, int] = {}
    for u in missing:
        by_role[u["role"]] = by_role.get(u["role"], 0) + 1
        by_class[u["fixability_class"]] = by_class.get(u["fixability_class"], 0) + 1

    # One merged window per distinct fixable symbol (a provider call batches a
    # symbol's whole date range), but report the granular symbol-date count too.
    fixable = [u for u in missing if u["fixability_class"] in FIXABLE_CLASSES]
    per_symbol: dict[str, dict] = {}
    for u in fixable:
        s = u["symbol"]
        w = per_symbol.setdefault(s, {"symbol": s, "start": u["window_start"], "end": u["window_end"], "events": 0})
        w["start"] = min(w["start"], u["window_start"]) if w["start"] and u["window_start"] else (w["start"] or u["window_start"])
        w["end"] = max(w["end"], u["window_end"]) if w["end"] and u["window_end"] else (w["end"] or u["window_end"])
        w["events"] += 1
    planned_windows = sorted(per_symbol.values(), key=lambda w: -w["events"])

    return {
        "scenario": scenario,
        "snapshot": snapshot,
        "missing_units": missing,
        "by_role": by_role,
        "by_class": by_class,
        "distinct_symbols": len(per_symbol),
        "symbol_date_windows": len(fixable),
        "planned_windows": planned_windows,
        "request_estimate": len(per_symbol),               # ~one batched fetch per symbol
        "est_cache_rows": len(per_symbol) * _APPROX_BARS_PER_WINDOW,  # approximate
        "disclaimer": DISCLAIMER,
    }


def summarize(plan: dict) -> str:
    s = plan["snapshot"]
    lines = [
        f"AR coverage repair plan - scenario: {plan['scenario']}  (DRY-RUN, read-only, zero-cost)",
        "",
        "Current coverage:",
        f"  beneficiary    {s['beneficiary']['covered']}/{s['beneficiary']['total']}",
        f"  loser/exposed  {s['loser']['covered']}/{s['loser']['total']}",
        f"  total          {s['total']['covered']}/{s['total']['total']}",
        "",
        f"Missing by role:  {plan['by_role']}",
        "Missing by fixability class:",
    ]
    for cls, n in sorted(plan["by_class"].items(), key=lambda kv: -kv[1]):
        fix = "fixable" if cls in FIXABLE_CLASSES else "not-fixable/manual"
        lines.append(f"  {cls:22} {n:4}  [{fix}]")
    lines += [
        "",
        "Proposed backfill (V2B, gated):",
        f"  distinct symbols       {plan['distinct_symbols']}",
        f"  symbol-date windows    {plan['symbol_date_windows']}",
        f"  est. provider requests {plan['request_estimate']}  (batchable, daily closes)",
        f"  est. cache rows        ~{plan['est_cache_rows']}  (approximate)",
        "",
        "Top planned windows (symbol: events  start..end):",
    ]
    for w in plan["planned_windows"][:15]:
        lines.append(f"  {w['symbol']:16} {w['events']:2}  {w['start']}..{w['end']}")
    lines += ["", plan["disclaimer"]]
    return "\n".join(lines)

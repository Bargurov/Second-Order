"""Recover legacy directional evidence from already-cached market data.

Root cause (diagnosed on a scratch copy of the archive): a cluster of
accepted events analyzed on/right after their event date (late April /
early May 2026) was persisted with ``return_5d = None`` because the 5-day
window had not elapsed yet, and the rows were never refreshed. The
canonical 5d-based ``direction_tag`` was therefore structurally
uncomputable at write time, leaving the events without directional
evidence even though the local ``price_cache`` table now holds the raw
event-anchored bars for the elapsed windows.

This module is a narrowly scoped, dry-run-first backfill that re-derives
ONLY the missing derived fields through the canonical market_check
primitives:

* bars come from ``market_check._fetch_since`` under
  ``market_data.no_provider_fetch()`` - strictly cache-only, the provider
  is structurally unreachable;
* returns come from ``market_check._pct_forward`` +
  ``market_check._sanitize_returns`` (the exact production pipeline);
* tags come from ``market_check._direction_tag`` (the production
  classifier, unchanged thresholds, unrounded-r5 input, flat zone
  preserved as non-directional).

Missingness is preserved everywhere the stored inputs stay insufficient:
no cached bars, a window not anchored at the original anchor session, an
unusable role, or a stored dual-source verification veto all leave the
ticker untouched. A ticker whose stored ``return_5d`` is already present
is never re-tagged - a present r5 with a cleared tag can be a deliberate
verification veto, and this module never overturns it. Stored values are
never overwritten; only ``None`` fields are filled. Selection is entirely
rule-based - the accepted gate (non-thesis stages and synthetic seeds
excluded) plus the zero-directional-evidence condition - with no event-id
allowlist.

Writes go through the established ``db.update_event_market_refresh``
writer (one transaction per event, proof/falsifier blocks recomputed by
the production code path), preserving the row's existing ``market_note``
and ``last_market_check_at`` so freshness semantics are unchanged. The
command defaults to dry-run and requires both an explicit ``--db-path``
and ``--apply`` to mutate anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import market_check  # noqa: E402
import market_data  # noqa: E402
from validation_status import _gather_ticker_signals  # noqa: E402

_USABLE_ROLES = ("beneficiary", "loser")
_VETO_STATUSES = ("disputed", "timed_out")


def _switch_db(db_path: str):
    saved_file, saved_ready = _db.DB_FILE, _db._db_ready
    _db.DB_FILE = str(db_path)
    _db._db_ready = True
    return saved_file, saved_ready


def _restore_db(saved) -> None:
    _db.DB_FILE, _db._db_ready = saved


def _accepted_events(db_path: str) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        synthetic = _db.synthetic_seed_ids(conn)
        rows = conn.execute("SELECT * FROM events").fetchall()
    finally:
        conn.close()
    accepted = []
    for row in rows:
        event = _db._decode_event_row(dict(row))
        stage = event.get("stage")
        if isinstance(stage, str) and stage in _db.NON_THESIS_STAGES:
            continue
        if event.get("id") in synthetic:
            continue
        accepted.append(event)
    return accepted


def _funnel(accepted: list[dict]) -> dict[str, int]:
    with_tickers = directional = 0
    for event in accepted:
        signals = _gather_ticker_signals(event.get("market_tickers"))
        if signals["total"] > 0:
            with_tickers += 1
            if signals["supporting"] + signals["contradicting"] > 0:
                directional += 1
    return {
        "accepted": len(accepted),
        "with_tickers": with_tickers,
        "directional": directional,
        "in_scope": with_tickers - directional,
        "no_tickers": len(accepted) - with_tickers,
    }


def _recover_ticker(ticker: Any, event_date: str) -> dict[str, Any]:
    """Plan entry for one stored ticker. Pure inspection + cache reads."""
    if not isinstance(ticker, dict):
        return {"symbol": None, "new_fields": {},
                "blocker": "malformed_entry"}
    symbol = ticker.get("symbol")
    entry: dict[str, Any] = {"symbol": symbol, "new_fields": {}}
    tag = ticker.get("direction_tag")
    if isinstance(tag, str) and tag:
        entry["blocker"] = "already_tagged"
        return entry
    if ticker.get("return_5d") is not None:
        # A present r5 with no tag can be a deliberate verification veto
        # (the production path clears the tag but keeps the number);
        # never re-derive over it.
        entry["blocker"] = "r5_present_tag_withheld"
        return entry
    verification = ticker.get("verification")
    vetoed = (isinstance(verification, dict)
              and verification.get("status") in _VETO_STATUSES)
    role = ticker.get("role")
    role_l = role.strip().lower() if isinstance(role, str) else ""
    if role_l not in _USABLE_ROLES:
        entry["blocker"] = "no_usable_role"
        return entry
    if vetoed:
        entry["tag_blocker"] = "verification_veto"
        return entry
    if not isinstance(event_date, str) or not event_date.strip():
        entry["blocker"] = "no_event_date_anchor"
        return entry

    fetch_symbol = market_check._clean_fetch_symbol(str(symbol or ""))
    if not fetch_symbol:
        entry["blocker"] = "malformed_entry"
        return entry
    with market_data.no_provider_fetch():
        data = market_check._fetch_since(fetch_symbol, event_date)
    if data is None or len(data) == 0 or "Close" not in data.columns:
        entry["blocker"] = "no_cached_bars"
        return entry

    # The recomputed window must anchor where the original analysis
    # anchored: the stored per-ticker anchor_date when present, else the
    # clamped event date. A cache window starting elsewhere is not the
    # same measurement and is skipped, preserving missingness.
    recomputed_anchor = str(data.index[0].date())
    expected_anchor = ticker.get("anchor_date") or \
        market_check._clamp_to_market_date(event_date)
    if recomputed_anchor != expected_anchor:
        entry["blocker"] = "window_not_anchored"
        return entry

    closes = data["Close"]
    r1 = market_check._pct_forward(closes, 1)
    r5 = market_check._pct_forward(closes, 5)
    r20 = market_check._pct_forward(closes, 20)
    r1, r5, r20 = market_check._sanitize_returns(r1, r5, r20)

    new_fields: dict[str, Any] = {}
    for key, value in (("return_1d", r1), ("return_5d", r5),
                       ("return_20d", r20)):
        if ticker.get(key) is None and value is not None:
            new_fields[key] = round(value, 2)
    if r5 is None:
        entry["tag_blocker"] = "no_cached_5d_window"
    else:
        # Canonical classifier on the unrounded sanitized r5, exactly as
        # the production path does; a flat-zone None stays non-directional.
        derived = market_check._direction_tag(r5, role_l)
        if derived is not None:
            new_fields["direction_tag"] = derived
        else:
            entry["tag_blocker"] = "flat_zone"
    entry["new_fields"] = new_fields
    return entry


def build_recovery_plan(db_path: str) -> dict[str, Any]:
    """Read-only recovery plan over the accepted, in-scope events."""
    db_path = str(db_path)
    if not Path(db_path).exists():
        raise ValueError(f"database not found: {db_path}")
    saved = _switch_db(db_path)
    try:
        # The market_check since-cache is keyed by symbol+date only; clear
        # it so plans never leak bars across database files.
        with market_check._cache_lock:
            market_check._cache_data.clear()
        accepted = _accepted_events(db_path)
        funnel = _funnel(accepted)
        events: list[dict[str, Any]] = []
        for event in accepted:
            signals = _gather_ticker_signals(event.get("market_tickers"))
            if signals["total"] == 0:
                continue
            if signals["supporting"] + signals["contradicting"] > 0:
                continue
            tickers = [
                _recover_ticker(t, event.get("event_date"))
                for t in event.get("market_tickers") or []
            ]
            events.append({
                "event_id": event.get("id"),
                "event_date": event.get("event_date"),
                "stage": event.get("stage"),
                "tickers": tickers,
                "eligible": any(t["new_fields"] for t in tickers),
            })
        events.sort(key=lambda e: (e["event_id"] is None, e["event_id"]))
        return {"db_path": db_path, "funnel": funnel, "events": events}
    finally:
        _restore_db(saved)


def _merged_tickers(stored: list, plan_tickers: list[dict]) -> list:
    merged = []
    for original, planned in zip(stored, plan_tickers):
        if not isinstance(original, dict) or not planned["new_fields"]:
            merged.append(original)
            continue
        updated = dict(original)
        updated.update(planned["new_fields"])
        merged.append(updated)
    return merged


def run_recovery(db_path: str, *, apply: bool = False) -> dict[str, Any]:
    """Dry-run (default) or apply the recovery plan.

    Apply routes every write through ``db.update_event_market_refresh``
    (one transaction per event; proof/falsifier blocks recomputed by the
    production writer), passing the row's existing ``market_note`` and
    ``last_market_check_at`` through unchanged. Idempotent: a second
    apply finds no ``None`` fields left to fill and changes zero rows.
    """
    import sqlite3

    plan = build_recovery_plan(db_path)
    counts = {"selected": len(plan["events"]),
              "eligible": sum(1 for e in plan["events"] if e["eligible"]),
              "changed": 0, "skipped": 0, "failed": 0}
    result: dict[str, Any] = {"applied": bool(apply), "counts": counts,
                              "funnel_before": plan["funnel"],
                              "events": plan["events"]}
    if not apply:
        counts["skipped"] = counts["selected"]
        return result

    saved = _switch_db(db_path)
    try:
        for event_plan in plan["events"]:
            if not event_plan["eligible"]:
                counts["skipped"] += 1
                continue
            event_id = event_plan["event_id"]
            try:
                conn = sqlite3.connect(db_path)
                try:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT market_tickers, market_note, "
                        "last_market_check_at FROM events WHERE id = ?",
                        (event_id,)).fetchone()
                finally:
                    conn.close()
                if row is None:
                    counts["failed"] += 1
                    continue
                stored = json.loads(row["market_tickers"] or "[]")
                merged = _merged_tickers(stored, event_plan["tickers"])
                ok = _db.update_event_market_refresh(
                    event_id, merged,
                    row["market_note"] or "",
                    row["last_market_check_at"] or "")
                if ok:
                    counts["changed"] += 1
                else:
                    counts["failed"] += 1
            except Exception:
                counts["failed"] += 1
        result["funnel_after"] = _funnel(_accepted_events(db_path))
        return result
    finally:
        _restore_db(saved)


def main(argv=None) -> int:  # pragma: no cover - CLI seam
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True,
                        help="events database to plan against (never "
                             "defaults to the live archive)")
    parser.add_argument("--apply", action="store_true",
                        help="apply the recovery; default is dry-run")
    args = parser.parse_args(argv)
    result = run_recovery(args.db_path, apply=args.apply)
    out = {
        "applied": result["applied"],
        "counts": result["counts"],
        "funnel_before": result["funnel_before"],
        "funnel_after": result.get("funnel_after"),
        "events": [
            {"event_id": e["event_id"], "eligible": e["eligible"],
             "tickers": [
                 {"symbol": t.get("symbol"),
                  "new_fields": t["new_fields"],
                  "blocker": t.get("blocker"),
                  "tag_blocker": t.get("tag_blocker")}
                 for t in e["tickers"]]}
            for e in result["events"]],
    }
    sys.stdout.buffer.write(
        json.dumps(out, indent=1).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only sector-baseline AVAILABILITY report.

For the 86 accepted thesis rows (and the N1 walkthrough cases), this report
answers one narrow, honest question: is a *suggested* sector ETF baseline
locally cached and computable at the 1d / 5d / 20d event windows, and what was
that sector ETF's OWN raw window move - as descriptive context beside the
existing SPY-based event-study layer?

It is an availability / gating report ONLY. Crucial boundaries:

  * **SPY stays canonical.** The event-study abnormal return remains
    SPY-relative; ``BENCHMARK_TICKER`` and the engine math are untouched.
  * **The sector ETF is a hint, not a correction.** The suggestion reuses the
    existing ``sector_benchmark_suggestion_report._classify`` taxonomy; a
    row with no confident sector falls back to broad/SPY and is flagged,
    never forced.
  * **No sector-relative abnormal return is ever computed.** The only sector
    number is the ETF's own raw window change (descriptive backdrop). An
    asset-return-minus-sector-return read would be a separate, engine-touching
    step (a possible later O2), explicitly out of scope here.
  * **Cached != computable-at-date.** A cached ETF with no contiguous window at
    the event date is marked unavailable; missing windows are surfaced, never
    backfilled or fetched.

Usage::

    python scripts/sector_baseline_availability_report.py --db-path events.db --json
    python scripts/sector_baseline_availability_report.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from event_study_validation import (  # noqa: E402
    BENCHMARK_TICKER,
    HORIZONS,
    _business_day_offset,
    _is_contiguous,
    _last_index_le,
    _parse_iso_date,
    _primary_ticker,
)
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402
from scripts.sector_benchmark_suggestion_report import (  # noqa: E402
    _SECTOR_BENCHMARK,
    _classify,
)
from scripts.track_record_sensitivity_report import (  # noqa: E402
    _load_accepted_records,
)

DEFAULT_EXAMPLES = 3
# A distinct sector ETF (not the broad/SPY fallback) only at these confidences.
_DISTINCT_CONFIDENCE = frozenset({"high", "medium"})

_SPY_NOTE = (
    "Abnormal return remains SPY-relative (canonical); the sector move above is "
    "the ETF's own raw window change - descriptive backdrop only, not a "
    "sector-relative abnormal return."
)

NON_CLAIMS: tuple[str, ...] = (
    "No benchmark replacement: SPY remains the canonical abnormal-return "
    "benchmark; the sector ETF is a hint, not a correction.",
    "No event-study math change: the engine and BENCHMARK_TICKER are "
    "untouched.",
    "No sector-relative AR/SAR/CAR is computed; the sector move shown is the "
    "ETF's own raw window change, descriptive only.",
    "No significance is claimed (n=1; no CI, p-value, or FDR).",
    "No family-level inference and no performance ranking.",
    "Not a recommendation of any kind.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No database or price_cache mutation; nothing was backfilled or fetched.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record.",
)

_INTERPRETATION = {
    "what_sector_context_helps_clarify": (
        "Whether a named asset's SPY-relative move coincided with its sector "
        "moving the same way - a sector that moved with the asset is context a "
        "SPY-only read does not show."),
    "what_it_does_not_prove": (
        "Nothing causal or statistical: the sector's own move is descriptive, "
        "n=1, and says nothing about the asset's abnormal return."),
    "why_spy_remains_canonical": (
        "SPY is one consistent, broad benchmark for every event; per-event "
        "sector benchmarks introduce a benchmark-choice degree of freedom, so "
        "SPY stays the canonical abnormal-return benchmark and the sector is "
        "only a hint."),
    "why_this_is_not_sector_relative_abnormal_return": (
        "This report never recomputes the asset's return minus the sector "
        "ETF's return; it only reports whether the sector window is cached and "
        "what the sector ETF itself did. A sector-relative abnormal return "
        "would be a separate, engine-touching step (a possible later O2), "
        "out of scope here."),
}


# ---------------------------------------------------------------------------
# Pure availability gate (cached != computable-at-date)
# ---------------------------------------------------------------------------


def sector_window_availability(event_date_iso: Any,
                               closes: dict[str, float]
                               ) -> tuple[dict[int, dict], dict[int, Any]]:
    """Return (availability-by-horizon, raw-move-by-horizon) for one ETF.

    Mirrors the event-study engine's contiguity gate: an anchor close at/before
    the event date, a cached close at/after the horizon's business-day target,
    and a contiguous window between them. The raw move is the ETF's OWN
    ``exit/entry - 1`` - never an abnormal return, never vs SPY.
    """
    avail: dict[int, dict] = {}
    raw: dict[int, Any] = {}

    def _all(reason: str):
        for h in HORIZONS:
            avail[h] = {"available": False, "reason": reason}
            raw[h] = None
        return avail, raw

    if not closes:
        return _all("sector_etf_not_cached")
    ed = _parse_iso_date(event_date_iso if isinstance(event_date_iso, str)
                         else "")
    if ed is None:
        return _all("unparseable_event_date")

    dates = sorted(closes)
    ev_iso = str(event_date_iso)[:10]
    entry_idx = _last_index_le(dates, ev_iso)
    for h in HORIZONS:
        if entry_idx is None:
            avail[h] = {"available": False, "reason": "no_pre_event_close"}
            raw[h] = None
            continue
        target = _business_day_offset(ed, h).isoformat()
        exit_idx = None
        for i in range(entry_idx, len(dates)):
            if dates[i] >= target:
                exit_idx = i
                break
        if exit_idx is None:
            avail[h] = {"available": False,
                        "reason": f"forward_window_not_cached_{h}d"}
            raw[h] = None
            continue
        window = dates[entry_idx:exit_idx + 1]
        if not _is_contiguous(window):
            avail[h] = {"available": False,
                        "reason": f"non_contiguous_window_{h}d"}
            raw[h] = None
            continue
        entry_close = closes[dates[entry_idx]]
        exit_close = closes[dates[exit_idx]]
        if isinstance(entry_close, (int, float)) and entry_close > 0:
            raw[h] = round(exit_close / entry_close - 1.0, 6)
            avail[h] = {"available": True, "reason": None}
        else:
            avail[h] = {"available": False,
                        "reason": f"nonpositive_entry_close_{h}d"}
            raw[h] = None
    return avail, raw


# ---------------------------------------------------------------------------
# Loaders (read-only)
# ---------------------------------------------------------------------------


def _load_accepted_for_sector(db_path: str | None) -> list[dict]:
    records, _ = _load_accepted_records(db_path)
    by_id = {r["event_id"]: r for r in records}
    ids = list(by_id)
    extra: dict[int, dict] = {}
    if db_path and ids:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            idset = set(ids)
            for r in conn.execute(
                    "SELECT id, event_date, market_tickers FROM events"):
                if r["id"] in idset:
                    extra[r["id"]] = {"event_date": r["event_date"],
                                      "market_tickers": r["market_tickers"]}
            conn.close()
        except sqlite3.Error:
            extra = {}
    rows = []
    for eid, rec in by_id.items():
        ex = extra.get(eid, {})
        rows.append({
            "event_id": eid,
            "headline": rec["headline"],
            "event_date": ex.get("event_date"),
            "primary_ticker": _primary_ticker(ex.get("market_tickers")),
        })
    rows.sort(key=lambda r: r["event_id"])
    return rows


def _load_denominators(db_path: str | None) -> dict[str, Any]:
    rep = edq_build_report(db_path=db_path, lens="accepted", limit=0)
    d = rep.get("denominators", {})
    return {k: d.get(k) for k in (
        "archive_rows", "accepted_coverage_denominator",
        "accepted_track_record_denominator", "staged_candidate_count")}


def _load_etf_closes(db_path: str | None,
                     etfs: set[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not db_path or not etfs:
        return out
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        for etf in etfs:
            closes: dict[str, float] = {}
            # Raw basis preferred (broadest coverage, matches the engine's raw
            # SPY choice); fall back to adjusted if no raw bars are cached.
            for auto_adjust in (0, 1):
                try:
                    rows = conn.execute(
                        "SELECT date, close FROM price_cache WHERE ticker = ? "
                        "AND auto_adjust = ? AND close IS NOT NULL ORDER BY date",
                        (etf.upper(), auto_adjust)).fetchall()
                except sqlite3.Error:
                    rows = []
                for raw_date, raw_close in rows:
                    if isinstance(raw_date, str) and raw_close is not None:
                        try:
                            closes[raw_date[:10]] = float(raw_close)
                        except (TypeError, ValueError):
                            pass
                if closes:
                    break
            out[etf] = closes
    finally:
        conn.close()
    return out


def _walkthrough_case_ids(db_path: str | None) -> list[int]:
    try:
        from scripts.transmission_case_walkthrough_report import (
            build_walkthrough,
        )
        rep = build_walkthrough(db_path=db_path)
        return [c["event_id"] for c in rep.get("selected_cases", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _clip(text: Any, n: int = 140) -> str:
    t = str(text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _safe(text: str) -> str:
    return str(text or "").encode("cp1252", "replace").decode("cp1252")


def _missingness_note(distinct: bool, benchmark: str,
                      avail: dict[int, dict]) -> str:
    if not distinct:
        return ("Suggestion fell back to broad/SPY; no distinct sector ETF to "
                "provide context for this row.")
    avail_h = [h for h in HORIZONS if avail[h]["available"]]
    miss_h = [h for h in HORIZONS if not avail[h]["available"]]
    if not miss_h:
        return ""
    if not avail_h:
        reasons = sorted({avail[h]["reason"] for h in miss_h})
        return f"Sector ETF {benchmark} has no computable window: {reasons}."
    return (f"Sector ETF {benchmark} computable at "
            f"{[f'{h}d' for h in avail_h]}; missing at "
            f"{[f'{h}d' for h in miss_h]}.")


def _assemble_row(row: dict, benchmark: str, confidence: str, rationale: str,
                  distinct: bool, avail: dict, raw: dict) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "headline": _clip(row.get("headline")),
        "event_date": row.get("event_date"),
        "suggested_sector_etf": benchmark,
        "suggestion_confidence": confidence,
        "suggestion_reason": rationale,
        "availability": {
            "horizon_1d": avail[1],
            "horizon_5d": avail[5],
            "horizon_20d": avail[20],
        },
        "sector_raw_moves": {
            "horizon_1d": raw[1],
            "horizon_5d": raw[5],
            "horizon_20d": raw[20],
        },
        "missingness_note": _missingness_note(distinct, benchmark, avail),
        "spy_canonical_note": _SPY_NOTE,
    }


def build_report(db_path: str | None = None, *,
                 rows: list[dict] | None = None,
                 denominators: dict | None = None,
                 closes_by_ticker: dict | None = None,
                 walkthrough_case_ids: Sequence[int] | None = None,
                 include_examples: int = DEFAULT_EXAMPLES) -> dict[str, Any]:
    """Build the sector-baseline availability report. Read-only."""
    if rows is None:
        rows = _load_accepted_for_sector(db_path)
    if denominators is None:
        denominators = _load_denominators(db_path)

    classified = []
    needed_etfs: set[str] = set()
    for row in rows:
        sector, benchmark, confidence, rationale = _classify(
            ticker=row.get("primary_ticker"), headline=row.get("headline"))
        distinct = confidence in _DISTINCT_CONFIDENCE
        if distinct:
            needed_etfs.add(benchmark)
        classified.append((row, benchmark, confidence, rationale, distinct))

    if closes_by_ticker is None:
        closes_by_ticker = _load_etf_closes(db_path, needed_etfs)

    out_rows = []
    for row, benchmark, confidence, rationale, distinct in classified:
        if distinct:
            avail, raw = sector_window_availability(
                row.get("event_date"), closes_by_ticker.get(benchmark, {}))
        else:
            avail = {h: {"available": False,
                         "reason": "fallback_broad_spy_no_distinct_sector"}
                     for h in HORIZONS}
            raw = {h: None for h in HORIZONS}
        out_rows.append(_assemble_row(row, benchmark, confidence, rationale,
                                     distinct, avail, raw))

    summary = _availability_summary(out_rows, classified)

    if walkthrough_case_ids is None:
        walkthrough_case_ids = _walkthrough_case_ids(db_path)
    wc_ids = list(walkthrough_case_ids or [])
    by_id = {r["event_id"]: r for r in out_rows}
    wc_cases = [by_id[i] for i in wc_ids if i in by_id]

    return {
        "denominators": dict(denominators),
        "scope": {
            "read_only": True,
            "spy_canonical_benchmark": True,
            "engine_math_changed": False,
            "sector_is_hint_not_correction": True,
            "no_sector_abnormal_return": True,
            "no_backfill": True,
        },
        "sector_baseline_policy": {
            "suggestion_source": ("scripts/sector_benchmark_suggestion_report."
                                  "_classify (reused, read-only)"),
            "supported_sector_universe": sorted(set(_SECTOR_BENCHMARK.values())),
            "fallback_policy": ("no confident sector -> broad/SPY at "
                                "confidence low/none; no distinct sector "
                                "context, flagged for manual review"),
            "availability_requires_cached_contiguous_window": True,
        },
        "accepted_availability_summary": summary,
        "rows": out_rows,
        "n1_walkthrough_cases": {
            "selected_case_ids": wc_ids,
            "cases": wc_cases,
        },
        "interpretation": dict(_INTERPRETATION),
        "non_claims": list(NON_CLAIMS),
    }


def _availability_summary(out_rows: list[dict], classified: list) -> dict:
    distinct_by_id = {row["event_id"]: distinct
                      for row, _b, _c, _r, distinct in classified}
    accepted_rows = len(out_rows)
    suggested = sum(1 for v in distinct_by_id.values() if v)

    def _avail(h):
        return sum(1 for r in out_rows
                   if r["availability"][f"horizon_{h}d"]["available"])

    unavailable = sum(
        1 for r in out_rows
        if not any(r["availability"][f"horizon_{h}d"]["available"]
                   for h in HORIZONS))
    reasons = Counter(
        r["availability"]["horizon_20d"]["reason"]
        for r in out_rows
        if not r["availability"]["horizon_20d"]["available"])
    return {
        "accepted_rows": accepted_rows,
        "suggested_sector_count": suggested,
        "fallback_or_manual_review_count": accepted_rows - suggested,
        "available_1d_count": _avail(1),
        "available_5d_count": _avail(5),
        "available_20d_count": _avail(20),
        "unavailable_count": unavailable,
        "unavailable_reasons": dict(reasons),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_move(v: Any) -> str:
    return f"{v:+.4f}" if isinstance(v, float) else "-"


def _avail_mark(cell: dict) -> str:
    return "yes" if cell["available"] else f"no({cell['reason']})"


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("Sector-baseline availability (read-only) - SPY stays canonical")
    add("=" * 62)
    d = report["denominators"]
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']}")
    add("Sector ETF = hint, not a correction. No sector-relative abnormal "
        "return is computed; SPY remains the canonical benchmark.")
    add("")

    s = report["accepted_availability_summary"]
    add("Accepted availability summary:")
    add(f"  accepted rows {s['accepted_rows']} | suggested-sector "
        f"{s['suggested_sector_count']} | broad/SPY fallback "
        f"{s['fallback_or_manual_review_count']}")
    add(f"  sector window available: 1d {s['available_1d_count']} | 5d "
        f"{s['available_5d_count']} | 20d {s['available_20d_count']} | "
        f"none {s['unavailable_count']}")
    if s["unavailable_reasons"]:
        add(f"  unavailable reasons (20d): {s['unavailable_reasons']}")
    add("")

    wc = report["n1_walkthrough_cases"]
    add(f"N1 walkthrough cases ({wc['selected_case_ids']}) - sector backdrop:")
    for c in wc["cases"]:
        a = c["availability"]
        rm = c["sector_raw_moves"]
        add(f"  [{c['event_id']}] sector {c['suggested_sector_etf']} "
            f"({c['suggestion_confidence']}) | 1d {_avail_mark(a['horizon_1d'])}"
            f" {_fmt_move(rm['horizon_1d'])} | 5d "
            f"{_avail_mark(a['horizon_5d'])} {_fmt_move(rm['horizon_5d'])} | "
            f"20d {_avail_mark(a['horizon_20d'])} {_fmt_move(rm['horizon_20d'])}")
    add("")

    cap = max(int(report.get("_examples", DEFAULT_EXAMPLES)
                  if isinstance(report.get("_examples"), int)
                  else DEFAULT_EXAMPLES), 0)
    avail_rows = [r for r in report["rows"]
                  if r["availability"]["horizon_20d"]["available"]]
    miss_rows = [r for r in report["rows"]
                 if not any(r["availability"][f"horizon_{h}d"]["available"]
                            for h in HORIZONS)]
    add("Examples - sector window available (20d):")
    for r in avail_rows[:cap]:
        rm = r["sector_raw_moves"]
        add(f"  [{r['event_id']}] {r['suggested_sector_etf']} 20d move "
            f"{_fmt_move(rm['horizon_20d'])}  {_safe(_clip(r['headline'], 60))}")
    if not avail_rows:
        add("  (none)")
    add("Examples - sector window unavailable/missing:")
    for r in miss_rows[:cap]:
        add(f"  [{r['event_id']}] {r['suggested_sector_etf']}: "
            f"{_safe(_clip(r['missingness_note'], 80))}")
    if not miss_rows:
        add("  (none)")
    add("")

    add("Non-claims:")
    for item in report["non_claims"]:
        add(f"  - {_safe(item)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only sector-baseline availability report "
                    "(SPY stays canonical).")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-examples", type=int, default=DEFAULT_EXAMPLES)
    parser.add_argument("--include-walkthrough-cases", action="store_true",
                        help="(default on) include the N1 walkthrough cases")
    args = parser.parse_args(argv)

    report = build_report(db_path=args.db_path,
                          include_examples=args.include_examples)
    report["_examples"] = args.include_examples
    if args.json:
        report.pop("_examples", None)
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

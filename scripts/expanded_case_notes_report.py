#!/usr/bin/env python3
"""Read-only expanded case notes for the 9 newly proposed F1 cases (F2).

For the nine cases F1 newly proposed (7, 29, 38, 71, 153, 154, 160, 212, 239)
this report renders a compact, source-grounded note a finance reviewer can read:
event -> mechanism -> assets/proxies -> 1d/5d/20d SPY-relative readout (if
available) -> why selected (the deterministic F1 reason) -> caveats/falsifier ->
non-claim. The six N1 anchors (1, 46, 61, 66, 210, 211) are referenced but NOT
rewritten here, and the N1 walkthrough is untouched.

It adds no new selection, no new analysis, no p-value, no FDR, no forecast, and
no trading language. Reuse only:
  * F1 (`representative_case_expansion_report.build_report`) for the selected
    cases' identity, family, outcome, event-study availability, selection
    reason, caveats, and event-date quality;
  * the event-study coverage report for the per-horizon SPY-relative readout;
  * read-only `events` fields for the mechanism text (verbatim; the honest
    "insufficient evidence" placeholders are surfaced, never replaced).

Lens discipline: the event-study readout is the primary ticker's abnormal return
vs SPY over the event window. It is a DIFFERENT lens from the
support/contradiction/unresolved outcome (thesis-direction scoring of the named
tickers) - so two same-date cases can share an identical readout yet carry
opposite outcomes (e.g. 29 vs 38). Each readout block says so.

Read-only throughout (mode=ro, reused tested helpers); no DB / price_cache write,
no paid call, no /analyze, no fetch.

Usage::

    python scripts/expanded_case_notes_report.py --db-path events.db --json
    python scripts/expanded_case_notes_report.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts.event_study_coverage_report import (  # noqa: E402
    summarize_event_study_coverage,
)
from scripts.representative_case_expansion_report import (  # noqa: E402
    N1_BASELINE_IDS,
    build_report as f1_build_report,
)

NEW_IDS: tuple[int, ...] = (7, 29, 38, 71, 153, 154, 160, 212, 239)
N1_ANCHOR_IDS: tuple[int, ...] = tuple(N1_BASELINE_IDS)

_HZ_LABEL = {1: "1d", 5: "5d", 20: "20d"}

READOUT_LENS_NOTE = (
    "Event-study readout is the primary ticker's abnormal return vs SPY over the "
    "event window - a different lens from the support / contradiction / "
    "unresolved outcome (thesis-direction scoring of the named tickers), not its "
    "basis. Descriptive only; not a significance claim."
)

NON_CLAIM = (
    "Illustrative case note only - not evidence, no family-level inference, no "
    "recommendation or forecast."
)

NON_CLAIMS: tuple[str, ...] = (
    "Expanded case notes are illustrative only; they add no new claim.",
    "No family-level inference; outcome labels are the canonical any_support "
    "vocabulary applied per event, descriptively.",
    "No pooled significance: no CI, p-value, or FDR is computed or implied.",
    "Event-study readouts are SPY-relative abnormal returns over the window, a "
    "different lens from the outcome and not a significance claim.",
    "Mechanism text is the record's own field, surfaced verbatim (including its "
    "honest insufficient-evidence placeholders); nothing is invented.",
    "Not a recommendation of any kind, and no forecast.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record; "
    "staged candidates (13) are excluded.",
)


# ---------------------------------------------------------------------------
# Pure assembly
# ---------------------------------------------------------------------------

def _fmt_pct(x: Any) -> float | None:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return round(float(x) * 100.0, 2)
    return None


def _fmt_ratio(x: Any) -> float | None:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return round(float(x), 2)
    return None


def _readout_block(entry: dict | None) -> dict:
    if not entry or not entry.get("per_horizon"):
        return {"available": False, "horizons": {},
                "note": "event-study readout unavailable for this case"}
    horizons: dict[str, dict] = {}
    for h, vals in entry["per_horizon"].items():
        ar, sar, car = (vals + (None, None, None))[:3] if isinstance(vals, tuple) else (None, None, None)
        horizons[_HZ_LABEL.get(h, str(h))] = {
            "ar_pct": _fmt_pct(ar), "sar": _fmt_ratio(sar), "car_pct": _fmt_pct(car),
        }
    return {
        "available": True,
        "benchmark": entry.get("benchmark"),
        "primary_ticker": entry.get("primary_ticker"),
        "horizons": horizons,
        "lens_note": READOUT_LENS_NOTE,
    }


def _mechanism_block(mech: dict | None) -> dict:
    mech = mech or {}
    ms = mech.get("mechanism_summary")
    wc = mech.get("what_changed")
    tc = mech.get("transmission_chain")
    ms = ms if (isinstance(ms, str) and ms.strip()) else None
    wc = wc if (isinstance(wc, str) and wc.strip()) else None
    tc = tc if isinstance(tc, list) else []
    return {
        "mechanism_summary": ms,
        "what_changed": wc,
        "transmission_chain": tc,
        "available": bool(ms or wc),
    }


def _assemble_note(case: dict, mech: dict | None, readout_entry: dict | None) -> dict:
    tickers = list(case.get("assets") or [])
    readout = _readout_block(readout_entry)
    assets = {
        "tickers": tickers,
        "event_study_primary": readout.get("primary_ticker") if readout["available"] else None,
        "benchmark": readout.get("benchmark") if readout["available"] else None,
        "note": ("available ticker fields do not rank primary vs secondary exposure"
                 if tickers else "no assets in the record"),
    }
    return {
        "event_id": case["event_id"],
        "headline": case.get("headline"),
        "event_date": case.get("event_date"),
        "family": case.get("family"),
        "outcome": case.get("outcome"),
        "event_study_available": bool(case.get("event_study_available")),
        "why_selected": case.get("representative_reason"),
        "mechanism": _mechanism_block(mech),
        "assets": assets,
        "readout": readout,
        "caveats": list(case.get("caveats") or []),
        "event_date_quality": case.get("event_date_quality"),
        "non_claim": NON_CLAIM,
    }


def build_notes(
    new_cases: Sequence[dict],
    *,
    mechanism_by_id: dict,
    readout_by_id: dict,
) -> list[dict]:
    """Assemble notes for the NEW_IDS cases, ordered by NEW_IDS. Pure."""
    order = {eid: i for i, eid in enumerate(NEW_IDS)}
    cases = sorted(
        [c for c in new_cases if c.get("event_id") in order],
        key=lambda c: order[c["event_id"]],
    )
    return [
        _assemble_note(c, mechanism_by_id.get(c["event_id"]),
                       readout_by_id.get(c["event_id"]))
        for c in cases
    ]


# ---------------------------------------------------------------------------
# Read-only DB wiring
# ---------------------------------------------------------------------------

def _mechanism_by_id(path: str | None, ids: Sequence[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if path is None:
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        conn.row_factory = sqlite3.Row
        qmarks = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, mechanism_summary, what_changed, transmission_chain "
            f"FROM events WHERE id IN ({qmarks})", tuple(ids),
        ).fetchall()
        for r in rows:
            tc_raw = r["transmission_chain"]
            try:
                tc = json.loads(tc_raw) if isinstance(tc_raw, str) else []
            except (ValueError, TypeError):
                tc = []
            out[r["id"]] = {
                "mechanism_summary": r["mechanism_summary"],
                "what_changed": r["what_changed"],
                "transmission_chain": tc if isinstance(tc, list) else [],
            }
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return out


def _readout_by_id(path: str | None, ids: Sequence[int]) -> dict[int, dict]:
    es = summarize_event_study_coverage(db_path=path, limit=10_000)
    wanted = set(ids)
    out: dict[int, dict] = {}
    for e in es.get("available", []):
        eid = e.get("event_id")
        if eid not in wanted:
            continue
        per = {}
        for p in e.get("per_horizon", []):
            per[p.get("horizon")] = (
                p.get("abnormal_return"), p.get("sar"), p.get("car"),
            )
        out[eid] = {
            "benchmark": e.get("benchmark"),
            "primary_ticker": e.get("primary_ticker"),
            "per_horizon": per,
        }
    return out


def build_report(*, db_path: str | None = None) -> dict:
    """Build the expanded-case-notes report. Read-only end to end."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    f1 = f1_build_report(db_path=path)
    new_cases = [c for c in f1["selected"] if c.get("role") == "newly_proposed"]

    mech = _mechanism_by_id(path, NEW_IDS)
    readout = _readout_by_id(path, NEW_IDS)
    notes = build_notes(new_cases, mechanism_by_id=mech, readout_by_id=readout)

    shared_primary = sorted(
        n["event_id"] for n in notes
        if n["readout"]["available"] and n["readout"].get("primary_ticker") == "XLE"
    )

    return {
        "purpose": (
            "Expanded, source-grounded notes for the 9 newly proposed F1 cases; "
            "the N1 anchors are referenced but not rewritten."
        ),
        "denominators": f1["denominators"],
        "new_ids": list(NEW_IDS),
        "n1_anchor_ids": list(N1_ANCHOR_IDS),
        "notes": notes,
        "missingness_summary": {
            "readout_unavailable_ids": [n["event_id"] for n in notes
                                        if not n["readout"]["available"]],
            "shared_xle_primary_ids": shared_primary,
            "shared_primary_note": (
                "Events sharing the XLE event-study primary on the same date have "
                "identical SPY-relative readouts; this is date clustering, not a "
                "repeated independent result."
            ),
            "mechanism_insufficient_ids": [
                n["event_id"] for n in notes
                if "insufficient" in (n["mechanism"]["mechanism_summary"] or "").lower()
                or "thin response" in (n["mechanism"]["mechanism_summary"] or "").lower()
            ],
        },
        "non_claims": list(NON_CLAIMS),
        "reproduce_command": (
            "python scripts/expanded_case_notes_report.py --db-path events.db --json"
        ),
    }


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------

def _cp1252(s: Any) -> str:
    """Make DB-sourced text cp1252-safe (Windows console)."""
    text = "" if s is None else str(s)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def render_text(report: dict) -> str:
    d = report.get("denominators", {})
    lines: list[str] = []
    lines.append("Expanded case notes - 9 newly proposed F1 cases (read-only)")
    lines.append("=" * 58)
    lines.append("")
    lines.append(
        f"Denominators: archive {d.get('archive_rows')} / coverage "
        f"{d.get('accepted_coverage_denominator')} / track-record "
        f"{d.get('accepted_track_record_denominator')} / event-study "
        f"{d.get('event_study_available_count')}/"
        f"{d.get('event_study_coverage_denominator')} / staged "
        f"{d.get('staged_candidates')} (excluded)"
    )
    lines.append(f"New ids: {report.get('new_ids')}")
    lines.append(f"N1 anchors (referenced, not rewritten): {report.get('n1_anchor_ids')}")
    lines.append("")
    for n in report.get("notes", []):
        lines.append(f"### Event {n['event_id']} - {_cp1252(n['headline'])}")
        lines.append(f"  Family lens : {n['family']}")
        lines.append(f"  Outcome     : {n['outcome']}")
        lines.append(f"  Event date  : {n['event_date']}  (anchor: {n['event_date_quality']})")
        lines.append(f"  Why selected: {n['why_selected']}")
        m = n["mechanism"]
        if m["available"]:
            if m["mechanism_summary"]:
                lines.append(f"  Mechanism   : {_cp1252(m['mechanism_summary'])}")
            if m["what_changed"]:
                lines.append(f"  What changed: {_cp1252(m['what_changed'])}")
        else:
            lines.append("  Mechanism   : mechanism text unavailable in the record")
        a = n["assets"]
        if a["tickers"]:
            primary = f" (event-study primary {a['event_study_primary']} vs {a['benchmark']})" if a["event_study_primary"] else ""
            lines.append(f"  Assets      : {', '.join(_cp1252(t) for t in a['tickers'])}{primary}")
            lines.append(f"                {a['note']}")
        else:
            lines.append(f"  Assets      : {a['note']}")
        rd = n["readout"]
        if rd["available"]:
            hz = rd["horizons"]
            def _h(k):
                v = hz.get(k, {})
                return f"AR {v.get('ar_pct')}% / SAR {v.get('sar')} / CAR {v.get('car_pct')}%"
            lines.append(f"  Readout     : 1d {_h('1d')} | 5d {_h('5d')} | 20d {_h('20d')}")
            lines.append(f"                {rd['lens_note']}")
        else:
            lines.append(f"  Readout     : {rd['note']}")
        if n["caveats"]:
            lines.append(f"  Caveats     : {'; '.join(_cp1252(c) for c in n['caveats'])}")
        lines.append(f"  Non-claim   : {n['non_claim']}")
        lines.append("")
    ms = report.get("missingness_summary", {})
    lines.append("Missingness / caveats summary:")
    lines.append(f"  readout unavailable: {ms.get('readout_unavailable_ids')}")
    lines.append(f"  shared XLE primary (same date): {ms.get('shared_xle_primary_ids')} - {ms.get('shared_primary_note')}")
    lines.append(f"  mechanism insufficient in record: {ms.get('mechanism_insufficient_ids')}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in report.get("non_claims", []):
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(f"Reproduce: {report.get('reproduce_command')}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only expanded case notes for the 9 newly proposed F1 cases.",
    )
    parser.add_argument("--db-path", default=None,
                        help="path to events.db (default: db.DB_FILE)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout

    report = build_report(db_path=args.db_path)
    if args.json:
        json.dump(report, stream, indent=2)  # ensure_ascii=True -> cp1252-safe
        stream.write("\n")
    else:
        stream.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

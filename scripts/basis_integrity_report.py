"""F2 basis-integrity comparison for the canonical event-study readouts.

The canonical gate resolves each readout's (asset, benchmark) auto_adjust
basis by a fallback preference order — matched raw/raw first, then matched
adjusted/adjusted, then the cross pairs.  That order is an implementation
detail, not a stated methodology policy, so the published readout set mixes
price-return rows (raw closes) with total-return rows (adjusted closes)
depending on cache shape.  This report quantifies what that mixture costs:

* it recomputes every cohort row under a FORCED matched raw/raw basis and a
  FORCED matched adjusted/adjusted basis (``flag_pairs`` on the gate — no
  silent fallback), and reports per-horizon deltas, sign changes, and
  availability under each basis;
* it flags a basis difference as an adjustment-factor step ONLY when the cache
  itself shows one — a step in the adjusted/raw close ratio inside the
  forward window (the specific cause is not classified); otherwise the row is
  labeled basis-sensitive with cause unresolved;
* it compares the current fallback policy with raw-only, adjusted-only, and
  adjusted-first-fallback alternatives on availability and basis mixture.

Denominator (stated before any result): the cohort is the **70** accepted
track-record rows whose canonical readout is event-study available.  The
archive's familiar **78 / 94** coverage lens is the accepted-coverage pool:
94 = 86 accepted track-record + 8 curated context rows; 78 available =
these 70 + the 8 curated rows (all ES-available), which are excluded here
because they are curated context, not track-record evidence.  Of the 86
accepted rows, 13 have no primary ticker and 3 are blocked by data gates.

This report restates nothing: the canonical readouts, outcomes, denominators,
representative cases, and closed FDR pools are unchanged.  Read-only: cached
closes only, no provider call, no fetch, no write.

Usage (read-only):

    python scripts/basis_integrity_report.py --db-path events.db
    python scripts/basis_integrity_report.py --db-path events.db --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from event_study_validation import (  # noqa: E402
    HORIZONS,
    STATUS_AVAILABLE as _ESV_AVAILABLE,
    _read_closes,
    build_event_study_validation,
)

FORCED_RAW: tuple[tuple[bool, bool], ...] = ((False, False),)
FORCED_ADJ: tuple[tuple[bool, bool], ...] = ((True, True),)

# A day-over-day step in the adjusted/raw close ratio larger than this marks an
# adjustment-factor step recorded in the cache (dividend-sized or larger); the
# specific cause is not classified.  Purely cache-internal evidence; no
# external source is consulted.
RATIO_STEP_THRESHOLD = 5e-4

# Descriptive |delta| buckets (absolute abnormal-return difference,
# adjusted-basis AR minus raw-basis AR).  Cuts are descriptive, not
# significance thresholds.
_BUCKETS = (
    ("lt_10bp", 0.0, 0.001),
    ("10_to_50bp", 0.001, 0.005),
    ("50_to_100bp", 0.005, 0.01),
    ("gte_100bp", 0.01, float("inf")),
)

NON_CLAIMS: tuple[str, ...] = (
    "Descriptive basis comparison only: no p-value, no CI, no FDR, no "
    "threshold of significance, and no new statistical model.",
    "This report does not restate any canonical number: the published "
    "readouts, outcome labels, accepted denominators (94 coverage / 86 "
    "track-record), representative cases, and closed Phase 1 / Phase 2 pools "
    "are unchanged.",
    "A basis difference is flagged as an adjustment-factor step only when the "
    "cached adjusted/raw close ratio itself steps inside the window (the "
    "specific cause is not classified); otherwise the row is labeled "
    "basis-sensitive with cause unresolved.",
    "Availability under a forced basis reflects the current cache only; "
    "nothing here fetches, backfills, or approximates a missing series.",
    "Not a recommendation of any trading action; no prediction about future "
    "returns of any asset.",
)


# ---------------------------------------------------------------------------
# Per-event forced-basis comparison
# ---------------------------------------------------------------------------


def _ar_by_h(payload: dict[str, Any]) -> dict[int, Optional[float]]:
    return {p.get("horizon"): p.get("abnormal_return")
            for p in (payload.get("per_horizon") or [])}


def _ratio_step_in_window(primary: str, event_date: Any) -> dict[str, bool]:
    """Cache-evidence adjustment-factor-step flags per horizon.

    Builds the adjusted/raw close ratio on the asset's both-flag common dates
    and reports, per horizon, whether the ratio steps by more than
    ``RATIO_STEP_THRESHOLD`` strictly after the event anchor and at or before
    the horizon's position in that calendar.  Read-only.
    """
    out = {f"{h}d": False for h in HORIZONS}
    raw = _read_closes(primary, auto_adjust=False)
    adj = _read_closes(primary, auto_adjust=True)
    common = sorted(set(raw) & set(adj))
    if not common:
        return out
    iso = str(event_date)[:10]
    anchor = None
    for i, d in enumerate(common):
        if d <= iso:
            anchor = i
    if anchor is None:
        return out
    steps: list[int] = []  # positions i where ratio steps between i-1 and i
    prev = None
    for i, d in enumerate(common):
        r = adj[d] / raw[d] if raw[d] else None
        if r is not None and prev is not None and prev != 0:
            if abs(r / prev - 1.0) > RATIO_STEP_THRESHOLD:
                steps.append(i)
        prev = r if r is not None else prev
    for h in HORIZONS:
        end = anchor + h
        out[f"{h}d"] = any(anchor < i <= end for i in steps)
    return out


def compare_bases(event: dict) -> dict[str, Any]:
    """Recompute one event's readout under forced raw/raw and adjusted/adjusted.

    Returns both payloads, per-horizon deltas (adjusted AR minus raw AR) when
    BOTH bases are computable (never a fabricated comparison otherwise), and
    the cache-evidence adjustment-factor-step flags.  Read-only.
    """
    raw = build_event_study_validation(event, flag_pairs=FORCED_RAW)
    adj = build_event_study_validation(event, flag_pairs=FORCED_ADJ)
    out: dict[str, Any] = {
        "event_id": (event or {}).get("id"),
        "raw": raw,
        "adjusted": adj,
        "deltas": [],
        "ratio_step_in_window": {f"{h}d": False for h in HORIZONS},
    }
    primary = raw.get("primary_ticker") or adj.get("primary_ticker")
    if primary:
        out["ratio_step_in_window"] = _ratio_step_in_window(
            primary, (event or {}).get("event_date"))
    if (raw.get("status") == _ESV_AVAILABLE
            and adj.get("status") == _ESV_AVAILABLE):
        raw_ar = _ar_by_h(raw)
        adj_ar = _ar_by_h(adj)
        for h in HORIZONS:
            r, a = raw_ar.get(h), adj_ar.get(h)
            if r is None or a is None:
                continue
            out["deltas"].append({
                "horizon": h,
                "raw_ar": r,
                "adjusted_ar": a,
                "adjusted_minus_raw_ar": a - r,
                "sign_change": (r > 0) != (a > 0) and r != 0 and a != 0,
            })
    return out


# ---------------------------------------------------------------------------
# Archive-wide report
# ---------------------------------------------------------------------------


def _comparability(cmp_: dict[str, Any]) -> str:
    r = cmp_["raw"].get("status") == _ESV_AVAILABLE
    a = cmp_["adjusted"].get("status") == _ESV_AVAILABLE
    if r and a:
        return "both_bases"
    if r:
        return "raw_only"
    if a:
        return "adjusted_only"
    return "neither"


def build_report(*, db_path: str | None = None) -> dict[str, Any]:
    """The full basis-integrity report over the canonical 70-row cohort.

    Points ``db.DB_FILE`` at the resolved path for the loop and restores it
    (same non-reentrant single-threaded-CLI contract as the sibling reports).
    Read-only throughout.
    """
    from scripts.effective_independent_evidence_report import _assemble_rows

    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    if path is None:
        return {"rows": [], "non_claims": list(NON_CLAIMS)}
    path = str(path)

    acc_rows, edq, coverage = _assemble_rows(path)
    cohort = [r for r in acc_rows
              if r["event_study_available"] and r.get("primary_ticker")]
    coverage_available_ids = {e.get("event_id")
                              for e in coverage.get("available", [])}
    accepted_ids = {r["event_id"] for r in acc_rows}
    curated_available = sorted(coverage_available_ids - accepted_ids)
    summary = (edq or {}).get("denominators", {})

    reconciliation = {
        "accepted_track_record": len(acc_rows),
        "cohort_size": len(cohort),
        "cohort_definition": (
            "accepted track-record rows whose canonical readout is "
            "event-study available (each has a primary ticker)"
        ),
        "accepted_no_primary": sum(
            1 for r in acc_rows if not r.get("primary_ticker")),
        "accepted_primary_blocked": sum(
            1 for r in acc_rows
            if r.get("primary_ticker") and not r["event_study_available"]),
        "coverage_lens_available": len(coverage_available_ids),
        "coverage_lens_denominator": summary.get(
            "accepted_coverage_denominator"),
        "curated_available_excluded": len(curated_available),
        "curated_available_ids": curated_available,
        "curated_exclusion_reason": (
            "curated context rows are a separate lens from the accepted "
            "track record; they are not canonical track-record readouts"
        ),
    }

    rows_out: list[dict[str, Any]] = []
    default_mixture = {"raw": 0, "adjusted": 0}
    saved = db.DB_FILE
    try:
        db.DB_FILE = path
        for r in cohort:
            event = {"id": r["event_id"], "event_date": r.get("date"),
                     "market_tickers": [{"symbol": r["primary_ticker"]}]}
            default = build_event_study_validation(event)
            cmp_ = compare_bases(event)
            basis = default.get("auto_adjust_basis") or {}
            if basis.get("asset") is True and basis.get("benchmark") is True:
                default_mixture["adjusted"] += 1
            elif basis.get("asset") is False and basis.get("benchmark") is False:
                default_mixture["raw"] += 1
            else:
                default_mixture["cross"] = default_mixture.get("cross", 0) + 1
            rows_out.append({
                "event_id": r["event_id"],
                "event_date": r.get("date"),
                "primary_ticker": r["primary_ticker"],
                "default_basis": basis,
                "comparability": _comparability(cmp_),
                "deltas": cmp_["deltas"],
                "ratio_step_in_window": cmp_["ratio_step_in_window"],
                "raw_blocking_reasons": (
                    cmp_["raw"].get("blocking_reasons") or []),
                "adjusted_blocking_reasons": (
                    cmp_["adjusted"].get("blocking_reasons") or []),
            })
    finally:
        db.DB_FILE = saved

    both = [r for r in rows_out if r["comparability"] == "both_bases"]
    raw_avail = sum(1 for r in rows_out
                    if r["comparability"] in ("both_bases", "raw_only"))
    adj_avail = sum(1 for r in rows_out
                    if r["comparability"] in ("both_bases", "adjusted_only"))

    # Delta distribution + sign changes over both-bases rows.
    distribution: dict[str, dict[str, Any]] = {}
    sign_changes: list[dict[str, Any]] = []
    for h in HORIZONS:
        abs_deltas = []
        for r in both:
            for d in r["deltas"]:
                if d["horizon"] != h:
                    continue
                abs_deltas.append(abs(d["adjusted_minus_raw_ar"]))
                if d["sign_change"]:
                    sign_changes.append({
                        "event_id": r["event_id"], "horizon": h,
                        "primary_ticker": r["primary_ticker"],
                        "raw_ar": d["raw_ar"], "adjusted_ar": d["adjusted_ar"],
                    })
        buckets = {name: 0 for name, _, _ in _BUCKETS}
        for v in abs_deltas:
            for name, lo, hi in _BUCKETS:
                if lo <= v < hi:
                    buckets[name] += 1
                    break
        distribution[f"{h}d"] = {
            "buckets": buckets,
            "n": len(abs_deltas),
            "max_abs": max(abs_deltas) if abs_deltas else None,
            "median_abs": statistics.median(abs_deltas) if abs_deltas else None,
        }

    # Materiality tiers (descriptive cuts, stated in the exhibit).
    def _max_abs_delta(r: dict[str, Any]) -> float:
        return max((abs(d["adjusted_minus_raw_ar"]) for d in r["deltas"]),
                   default=0.0)

    material = []
    for r in both:
        m = _max_abs_delta(r)
        has_sign = any(d["sign_change"] for d in r["deltas"])
        if m >= 0.01 or has_sign:
            material.append({
                "event_id": r["event_id"],
                "primary_ticker": r["primary_ticker"],
                "event_date": r["event_date"],
                "max_abs_delta": m,
                "sign_change": has_sign,
                "cache_ratio_step_evidence": any(
                    r["ratio_step_in_window"].values()),
                "attribution": (
                    "adjustment-factor step observed in the cached adjusted/raw "
                    "ratio inside the window (specific cause not classified)"
                    if any(r["ratio_step_in_window"].values())
                    else "basis-sensitive, cause unresolved"),
            })
    negligible = sum(1 for r in both if _max_abs_delta(r) < 0.001)

    policy_comparison = {
        "current_raw_first_fallback": {
            "semantics": "mixed: price returns where raw/raw aligns first, "
                         "total returns otherwise",
            "available": len(rows_out),
            "basis_mixture": default_mixture,
        },
        "raw_only": {
            "semantics": "price returns everywhere (dividends land in the AR)",
            "available": raw_avail,
            "availability_cost": len(rows_out) - raw_avail,
        },
        "adjusted_only": {
            "semantics": "total returns everywhere",
            "available": adj_avail,
            "availability_cost": len(rows_out) - adj_avail,
        },
        "adjusted_first_fallback": {
            "semantics": "total returns preferred; price returns only where "
                         "the adjusted pair is not computable (disclosed)",
            "available": len(rows_out),
            "basis_mixture": {
                "adjusted": adj_avail,
                "raw": len(rows_out) - adj_avail,
            },
        },
    }

    return {
        "denominator_reconciliation": reconciliation,
        "rows": rows_out,
        "availability": {
            "cohort": len(rows_out),
            "raw_basis_available": raw_avail,
            "adjusted_basis_available": adj_avail,
            "both_bases": len(both),
            "raw_only": sum(1 for r in rows_out
                            if r["comparability"] == "raw_only"),
            "adjusted_only": sum(1 for r in rows_out
                                 if r["comparability"] == "adjusted_only"),
            "neither": sum(1 for r in rows_out
                           if r["comparability"] == "neither"),
        },
        "delta_distribution": distribution,
        "sign_changes": sign_changes,
        "materiality": {
            "negligible_lt_10bp_rows": negligible,
            "material_rows": sorted(material,
                                    key=lambda m: -m["max_abs_delta"]),
            "material_definition": (
                "max |adjusted AR - raw AR| >= 100bp at any horizon, or a "
                "sign change at any horizon (descriptive cut, not a "
                "significance claim)"),
        },
        "policy_comparison": policy_comparison,
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering / CLI (read-only)
# ---------------------------------------------------------------------------


def _pct(v: Any) -> str:
    return "-" if v is None else f"{v * 100:+.2f}%"


def render_text(report: dict[str, Any]) -> str:
    rec = report.get("denominator_reconciliation", {})
    av = report.get("availability", {})
    L: list[str] = ["Basis-integrity report (read-only)", ""]
    L.append(
        f"Cohort: {rec.get('cohort_size')} canonical readouts "
        f"(= accepted {rec.get('accepted_track_record')} - "
        f"{rec.get('accepted_no_primary')} no-primary - "
        f"{rec.get('accepted_primary_blocked')} blocked); the familiar "
        f"{rec.get('coverage_lens_available')}/{rec.get('coverage_lens_denominator')} "
        f"coverage lens adds {rec.get('curated_available_excluded')} curated "
        f"context rows excluded here."
    )
    L.append(
        f"Availability: raw {av.get('raw_basis_available')} / adjusted "
        f"{av.get('adjusted_basis_available')} / both {av.get('both_bases')} "
        f"/ raw-only {av.get('raw_only')} / adjusted-only "
        f"{av.get('adjusted_only')} / neither {av.get('neither')}"
    )
    L.append("")
    L.append("Delta distribution |adjusted AR - raw AR| (both-bases rows):")
    for h, d in (report.get("delta_distribution") or {}).items():
        b = d["buckets"]
        L.append(
            f"  {h}: n={d['n']} <10bp {b['lt_10bp']} | 10-50bp "
            f"{b['10_to_50bp']} | 50-100bp {b['50_to_100bp']} | >=100bp "
            f"{b['gte_100bp']} | median {_pct(d['median_abs'])} max "
            f"{_pct(d['max_abs'])}"
        )
    sc = report.get("sign_changes") or []
    L.append(f"Sign changes: {len(sc)}")
    for s in sc:
        L.append(
            f"  #{s['event_id']} {s['primary_ticker']} {s['horizon']}d: raw "
            f"{_pct(s['raw_ar'])} -> adjusted {_pct(s['adjusted_ar'])}"
        )
    L.append("")
    mat = report.get("materiality", {})
    L.append(f"Materially basis-sensitive rows "
             f"({mat.get('material_definition')}):")
    for m in mat.get("material_rows", []):
        L.append(
            f"  #{m['event_id']} {m['primary_ticker']} {m['event_date']} "
            f"max|delta| {_pct(m['max_abs_delta'])} "
            f"sign_change={m['sign_change']} | {m['attribution']}"
        )
    L.append(f"Negligible (<10bp at every horizon): "
             f"{mat.get('negligible_lt_10bp_rows')}")
    L.append("")
    L.append("Policy comparison:")
    for name, p in (report.get("policy_comparison") or {}).items():
        mix = p.get("basis_mixture")
        cost = p.get("availability_cost")
        extra = (f" mixture={mix}" if mix is not None
                 else f" availability_cost={cost}")
        L.append(f"  {name}: available {p['available']}/"
                 f"{av.get('cohort')} | {p['semantics']} |{extra}")
    L.append("")
    for nc in report.get("non_claims", []):
        L.append(f"- {nc}")
    return "\n".join(L)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only basis-integrity comparison of the canonical "
            "event-study readouts under forced raw/raw and adjusted/adjusted "
            "bases. Restates nothing; no provider call, no write."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--db-path", dest="db_path", default=None)
    args = parser.parse_args(argv)
    report = build_report(db_path=args.db_path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

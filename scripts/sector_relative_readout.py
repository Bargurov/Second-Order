"""F1 sector-relative readout layer (read-only, descriptive).

Finance-native second lens on the event-study readout:

    absolute return -> vs SPY (canonical) -> vs sector benchmark -> 1d/5d/20d

**SPY stays canonical.** The archive's abnormal-return readout remains
SPY-relative with beta fixed at 1; this layer adds a second descriptive
comparison against the primary ticker's own sector ETF, computed by the SAME
gated engine (``build_event_study_validation`` with ``benchmark_ticker``) —
identical estimation-window, forward-cache, and contiguity discipline, beta
fixed at 1, no local beta, no factor model.

**Return semantics.** ``sector_relative_return`` is the hold-period abnormal
return (BHAR) against the sector ETF: ``(P_a(t+h)/P_a(t) - 1) -
(P_s(t+h)/P_s(t) - 1)`` — the identical arithmetic the canonical layer uses
for its SPY-relative ``abnormal_return``, with the benchmark swapped.  The
coverage summary's ``sector_vs_market_component`` is (SPY-relative AR) minus
(sector-relative AR) on basis-matched rows, which algebraically equals the
sector ETF's own excess return over SPY on the window: a property of the
(sector, window) pair, never an asset-specific quantity.  The two lenses are
independent gate calls and may resolve different auto_adjust bases or aligned
calendars for the same asset; rows where their raw returns disagree are
excluded from the component and disclosed, never silently mixed.

**Eligibility is deliberately narrow.** The ticker -> sector mapping is REUSED
verbatim from ``sector_benchmark_suggestion_report`` (the conservative,
reviewed map; DRIV/LIT-style thematic ETFs are deliberately absent there) and
is never extended here to maximise coverage.  Every state is explicit:

* ``sector_relative_available``   — mapped primary, sector window computable;
* ``sector_window_unavailable``   — mapped primary, but the sector ETF window
                                    is not cached/computable (reasons surfaced,
                                    never a fake fallback);
* ``asset_is_sector_benchmark``   — the primary IS a sector ETF (e.g. XLE);
                                    comparing it to itself is degenerate, so
                                    no sector-relative read is produced;
* ``asset_is_broad_benchmark``    — the primary is SPY itself;
* ``no_sector_benchmark``         — primary not in the conservative map
                                    (thematic/country ETFs, unmapped single
                                    names); SPY-only by design;
* ``no_primary_ticker``           — no readout primary at all.

Read-only: prices come from the cached ``price_cache`` table through the
existing validation gate; no provider/API call, no fetch, no backfill, no DB
write.  Descriptive only: no p-value, no FDR, no threshold; a sector-relative
residual does not establish company-specific causality.

Usage (read-only):

    python scripts/sector_relative_readout.py --db-path events.db
    python scripts/sector_relative_readout.py --db-path events.db --json
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
    BENCHMARK_TICKER,
    STATUS_AVAILABLE as _ESV_AVAILABLE,
    _primary_ticker,
    build_event_study_validation,
)
from scripts.sector_benchmark_suggestion_report import (  # noqa: E402
    _SECTOR_BENCHMARK,
    _TICKER_TO_SECTOR,
)

# The mapping is a verbatim reuse of the conservative suggestion-layer tables;
# version-stamped so any future change is an explicit, reviewable event.
MAPPING_VERSION = "sector-map v1 (reused verbatim from sector_benchmark_suggestion_report; no additions)"

# Distinct sector ETFs (the broad SPY fallback is not a sector).
SECTOR_ETFS = frozenset(v for k, v in _SECTOR_BENCHMARK.items() if k != "broad")

# Classification states (pure) — the readout statuses reuse the same strings
# for the non-computed cases so consumers see one vocabulary.
STATE_ELIGIBLE = "eligible"
STATE_SELF_BENCHMARK = "asset_is_sector_benchmark"
STATE_BROAD_BENCHMARK = "asset_is_broad_benchmark"
STATE_UNMAPPED = "no_sector_benchmark"
STATE_NO_PRIMARY = "no_primary_ticker"

STATUS_AVAILABLE = "sector_relative_available"
STATUS_WINDOW_UNAVAILABLE = "sector_window_unavailable"
STATUS_SELF_BENCHMARK = STATE_SELF_BENCHMARK
STATUS_BROAD_BENCHMARK = STATE_BROAD_BENCHMARK
STATUS_UNMAPPED = STATE_UNMAPPED
STATUS_NO_PRIMARY = STATE_NO_PRIMARY

ALL_STATUSES = frozenset({
    STATUS_AVAILABLE, STATUS_WINDOW_UNAVAILABLE, STATUS_SELF_BENCHMARK,
    STATUS_BROAD_BENCHMARK, STATUS_UNMAPPED, STATUS_NO_PRIMARY,
})

NON_CLAIMS: tuple[str, ...] = (
    "Descriptive sector-relative readout only: no p-value, no CI, no FDR, no "
    "threshold, and no new statistical machinery (beta fixed at 1, same "
    "convention as the canonical SPY-relative layer; no local beta, no factor "
    "model).",
    "SPY remains the canonical abnormal-return benchmark; this layer does not "
    "change any outcome label, accepted denominator, representative case, or "
    "closed FDR pool.",
    "A sector-relative residual does not establish company-specific causality; "
    "it only describes how the asset moved relative to one sector ETF over the "
    "window.",
    "Missing sector windows are reported as unavailable, never approximated; "
    "the ticker->sector map is the conservative suggestion-layer map, reused "
    "verbatim and never extended to maximise coverage.",
    "Not a recommendation of any kind; no prediction about future returns of "
    "any asset.",
)


# ---------------------------------------------------------------------------
# Pure classification
# ---------------------------------------------------------------------------


def classify_sector_benchmark(primary: Optional[str]) -> dict[str, Any]:
    """Classify a primary ticker's sector-benchmark eligibility. Pure.

    Returns ``{state, sector, benchmark}``; ``benchmark`` is set only for the
    ``eligible`` state.
    """
    if not primary or not isinstance(primary, str) or not primary.strip():
        return {"state": STATE_NO_PRIMARY, "sector": None, "benchmark": None}
    t = primary.strip().upper()
    if t == BENCHMARK_TICKER:
        return {"state": STATE_BROAD_BENCHMARK, "sector": None, "benchmark": None}
    if t in SECTOR_ETFS:
        return {"state": STATE_SELF_BENCHMARK,
                "sector": _TICKER_TO_SECTOR.get(t), "benchmark": None}
    sector = _TICKER_TO_SECTOR.get(t)
    if sector and sector != "broad":
        return {"state": STATE_ELIGIBLE, "sector": sector,
                "benchmark": _SECTOR_BENCHMARK[sector]}
    return {"state": STATE_UNMAPPED, "sector": None, "benchmark": None}


# ---------------------------------------------------------------------------
# Per-event readout
# ---------------------------------------------------------------------------


def build_sector_relative_readout(event: dict) -> dict[str, Any]:
    """Sector-relative readout for one event (read-only).

    Reuses the existing gated engine with the sector ETF as benchmark; every
    non-computable case is an explicit labeled state, never a fallback number.
    """
    primary = _primary_ticker((event or {}).get("market_tickers"))
    cls = classify_sector_benchmark(primary)
    out: dict[str, Any] = {
        "event_id": (event or {}).get("id"),
        "primary_ticker": primary,
        "sector": cls["sector"],
        "sector_benchmark": cls["benchmark"],
        "mapping_version": MAPPING_VERSION,
        "non_claims": list(NON_CLAIMS),
    }
    if cls["state"] != STATE_ELIGIBLE:
        out["status"] = cls["state"]
        return out

    payload = build_event_study_validation(
        event, benchmark_ticker=cls["benchmark"])
    if payload.get("status") != _ESV_AVAILABLE:
        out["status"] = STATUS_WINDOW_UNAVAILABLE
        out["blocking_reasons"] = list(payload.get("blocking_reasons") or [])
        return out

    per_horizon: list[dict[str, Any]] = []
    for row in payload.get("per_horizon") or []:
        per_horizon.append({
            "horizon": row.get("horizon"),
            "raw_return": row.get("raw_return"),
            "sector_return": row.get("benchmark_return"),
            "sector_relative_return": row.get("abnormal_return"),
        })
    out["status"] = STATUS_AVAILABLE
    out["per_horizon"] = per_horizon
    out["estimation_window_used"] = payload.get("estimation_window_used")
    if payload.get("basis_caveat"):
        out["basis_caveat"] = payload["basis_caveat"]
    return out


def compact_block(readout: dict[str, Any]) -> dict[str, Any]:
    """The per-row consumer form: the full readout minus the non-claims block
    (consumers carry one surface-level non-claim instead of 15 copies)."""
    return {k: v for k, v in readout.items() if k != "non_claims"}


# ---------------------------------------------------------------------------
# Archive-wide coverage / validation summary (read-only)
# ---------------------------------------------------------------------------


def summarize_sector_relative_coverage(*, db_path: str | None = None) -> dict[str, Any]:
    """Coverage + divergence summary over the 86 accepted rows (read-only).

    For each eligible row, computes BOTH lenses (canonical SPY-relative and
    sector-relative) so the reviewer can see where the two reads diverge.
    Points ``db.DB_FILE`` at the resolved path for the loop and restores it
    (same non-reentrant single-threaded-CLI contract as the sibling reports).
    """
    from scripts.effective_independent_evidence_report import _assemble_rows

    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    if path is None:
        return {"accepted_rows": 0, "counts": {}, "eligible_rows": [],
                "non_claims": list(NON_CLAIMS)}
    path = str(path)

    rows, _edq, _cov = _assemble_rows(path)
    counts = {"eligible": 0, "self_benchmark": 0, "broad_benchmark": 0,
              "unmapped": 0, "no_primary": 0}
    _COUNT_KEY = {
        STATE_ELIGIBLE: "eligible",
        STATE_SELF_BENCHMARK: "self_benchmark",
        STATE_BROAD_BENCHMARK: "broad_benchmark",
        STATE_UNMAPPED: "unmapped",
        STATE_NO_PRIMARY: "no_primary",
    }

    eligible_rows: list[dict[str, Any]] = []
    saved = db.DB_FILE
    try:
        db.DB_FILE = path
        for r in rows:
            cls = classify_sector_benchmark(r.get("primary_ticker"))
            counts[_COUNT_KEY[cls["state"]]] += 1
            if cls["state"] != STATE_ELIGIBLE:
                continue
            event = {"id": r["event_id"], "event_date": r.get("date"),
                     "market_tickers": [{"symbol": r["primary_ticker"]}]}
            sector = build_sector_relative_readout(event)
            spy = build_event_study_validation(event)
            spy_by_h = {p.get("horizon"): p
                        for p in (spy.get("per_horizon") or [])}
            detail: dict[str, Any] = {
                "event_id": r["event_id"],
                "event_date": r.get("date"),
                "primary_ticker": r["primary_ticker"],
                "sector": cls["sector"],
                "sector_benchmark": cls["benchmark"],
                "status": sector["status"],
            }
            if sector["status"] == STATUS_AVAILABLE:
                per_horizon = []
                mismatch = False
                for p in sector["per_horizon"]:
                    sp = spy_by_h.get(p["horizon"]) or {}
                    spy_raw = sp.get("raw_return")
                    if (p["raw_return"] is not None and spy_raw is not None
                            and abs(p["raw_return"] - spy_raw) > 1e-9):
                        mismatch = True
                    per_horizon.append({
                        "horizon": p["horizon"],
                        "raw_return": p["raw_return"],
                        "spy_raw_return": spy_raw,
                        "spy_abnormal_return": sp.get("abnormal_return"),
                        "sector_return": p["sector_return"],
                        "sector_relative_return": p["sector_relative_return"],
                    })
                detail["per_horizon"] = per_horizon
                # The two lenses are independent gate calls; they may resolve
                # different auto_adjust bases or aligned calendars for the SAME
                # asset.  When the raw returns disagree, the cross-lens
                # difference is contaminated by that basis/window artifact and
                # is excluded from the sector-vs-market component below.
                detail["cross_lens_basis_mismatch"] = mismatch
            else:
                detail["blocking_reasons"] = sector.get("blocking_reasons", [])
            eligible_rows.append(detail)
    finally:
        db.DB_FILE = saved

    # Sector-vs-market component: (SPY-relative AR) - (sector-relative AR).
    # On a shared asset basis this equals sector_return - spy_return — the
    # sector ETF's own excess move over SPY on the window.  It is a property
    # of the (sector ETF, window) pair, NOT an asset-specific quantity, and
    # duplicate same-window rows repeat the same value, so unique windows are
    # disclosed.  Rows whose two lenses resolved different bases/calendars
    # (raw returns disagree) are excluded and counted.
    matched = [r for r in eligible_rows
               if r["status"] == STATUS_AVAILABLE
               and not r["cross_lens_basis_mismatch"]]
    mismatched = [r for r in eligible_rows
                  if r["status"] == STATUS_AVAILABLE
                  and r["cross_lens_basis_mismatch"]]
    per_h: dict[str, dict[str, Any]] = {}
    for h in (1, 5, 20):
        deltas = []
        for row in matched:
            for p in row["per_horizon"]:
                if (p["horizon"] == h and p["spy_abnormal_return"] is not None
                        and p["sector_relative_return"] is not None):
                    deltas.append(p["spy_abnormal_return"]
                                  - p["sector_relative_return"])
        deltas.sort()
        per_h[f"{h}d"] = {
            "n": len(deltas),
            "min": deltas[0] if deltas else None,
            "median": statistics.median(deltas) if deltas else None,
            "max": deltas[-1] if deltas else None,
        }
    unique_windows = len({(r["sector_benchmark"], r["event_date"])
                          for r in matched + mismatched})
    component = {
        "definition": (
            "SPY-relative AR minus sector-relative AR on basis-matched rows; "
            "equals the sector ETF's own excess return over SPY on the window "
            "- a sector-vs-market (tape) component, not an asset-specific "
            "quantity. Duplicate same-window rows repeat the same value."
        ),
        "per_horizon": per_h,
        "rows_included": len(matched),
        "rows_excluded_basis_mismatch": len(mismatched),
        "excluded_event_ids": sorted(r["event_id"] for r in mismatched),
        "unique_windows": unique_windows,
    }

    available = sum(1 for r in eligible_rows if r["status"] == STATUS_AVAILABLE)
    return {
        "accepted_rows": len(rows),
        "mapping_version": MAPPING_VERSION,
        "counts": counts,
        "eligible_available": available,
        "eligible_window_unavailable": len(eligible_rows) - available,
        "eligible_rows": eligible_rows,
        "sector_vs_market_component": component,
        "non_claims": list(NON_CLAIMS) + [
            "This coverage summary does not change the accepted denominators "
            "(94 coverage / 86 track-record) or the event-study availability "
            "lens; it only describes where a second sector lens exists.",
        ],
    }


# ---------------------------------------------------------------------------
# Rendering / CLI (read-only)
# ---------------------------------------------------------------------------


def _pct(v: Any) -> str:
    return "-" if v is None else f"{v * 100:+.2f}%"


def render_text(cov: dict[str, Any]) -> str:
    L: list[str] = ["Sector-relative readout coverage (read-only)", ""]
    c = cov.get("counts", {})
    L.append(f"accepted rows: {cov.get('accepted_rows')} | mapping: {cov.get('mapping_version')}")
    L.append(
        f"  eligible {c.get('eligible', 0)} (available {cov.get('eligible_available', 0)}, "
        f"window-unavailable {cov.get('eligible_window_unavailable', 0)}) | "
        f"asset-is-sector-ETF {c.get('self_benchmark', 0)} | unmapped {c.get('unmapped', 0)} | "
        f"no-primary {c.get('no_primary', 0)} | SPY-primary {c.get('broad_benchmark', 0)}"
    )
    L.append("")
    L.append("Eligible rows (raw | vs SPY | vs sector), per horizon:")
    for r in cov.get("eligible_rows", []):
        head = (f"  #{r['event_id']} {r['event_date']} {r['primary_ticker']} "
                f"vs {r['sector_benchmark']} [{r['status']}]")
        L.append(head)
        for p in r.get("per_horizon") or []:
            L.append(
                f"    {p['horizon']:>2}d raw {_pct(p['raw_return'])} | "
                f"vs SPY {_pct(p['spy_abnormal_return'])} | "
                f"vs {r['sector_benchmark']} {_pct(p['sector_relative_return'])}"
            )
        if r.get("blocking_reasons"):
            L.append(f"    reasons: {', '.join(r['blocking_reasons'][:3])}")
        if r.get("cross_lens_basis_mismatch"):
            L.append("    note: SPY and sector lenses resolved different "
                     "bases/calendars for this asset (excluded from the "
                     "component below)")
    L.append("")
    comp = cov.get("sector_vs_market_component") or {}
    L.append("Sector-vs-market component (sector ETF return minus SPY return "
             "on the window; = SPY-relative AR minus sector-relative AR on "
             "basis-matched rows; a tape property, not asset-specific):")
    for h, d in (comp.get("per_horizon") or {}).items():
        L.append(
            f"  {h}: n={d['n']} min {_pct(d['min'])} | median {_pct(d['median'])} | "
            f"max {_pct(d['max'])}"
        )
    L.append(
        f"  rows included {comp.get('rows_included')} / excluded for "
        f"basis-mismatch {comp.get('rows_excluded_basis_mismatch')} "
        f"{comp.get('excluded_event_ids')} | unique (sector ETF, date) "
        f"windows {comp.get('unique_windows')} - duplicate same-window rows "
        f"repeat the same value"
    )
    L.append("")
    for nc in cov.get("non_claims", []):
        L.append(f"- {nc}")
    return "\n".join(L)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only sector-relative readout coverage over the accepted "
            "archive. Descriptive second lens beside the canonical "
            "SPY-relative readout; no DB write, no provider call."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--db-path", dest="db_path", default=None)
    args = parser.parse_args(argv)
    cov = summarize_sector_relative_coverage(db_path=args.db_path)
    if args.json:
        print(json.dumps(cov, indent=2, sort_keys=True, default=str))
    else:
        print(render_text(cov))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

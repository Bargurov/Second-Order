"""J1A outcome-blind data readiness and symmetric substrate (Mission J).

Contract: ``j1a-data-readiness-v1``, executing the locked j0-v1 constitution
(`stats/J0_FOMC_ROBUSTNESS_CONSTITUTION.md`) sections 8-10 and 13. This
slice prepares and verifies the data and calculation substrate for the 12
frozen J1 state-bearing cells WITHOUT computing or inspecting any J1
outcome: no event-window return value, no MEMP, no calibration, no node or
edge state, and no proxy ranking appears anywhere in this module's outputs.
Readiness is pure date/session geometry.

Reused seams (no second market-data framework, no second return engine):

- Treasury path: the ``g_state_acquisition`` official Treasury daily
  yield-curve CSV source and date semantics (the same parser columns), now
  persisting the ``2 Yr`` level the constitution found parsed-but-dropped.
- Equity path: ``g3_mechanical_grinder.fetch_yahoo_ohlc`` /
  ``build_price_db`` (Yahoo public chart endpoint, zero-cost), writing a
  NEW gitignored ``g_state_cache/j1a_price_cache.db`` so the Mission I
  substrate ``g3_price_cache.db`` stays byte-identical.
- Gate machinery: ``i1_candidate_universe`` frames/anchoring/era and the
  shipped ``event_study_validation`` contiguity guard.

Event and ordinary-reference anchors flow through the SAME readiness
functions; no membership argument exists on the measurement boundary.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import event_study_validation as esv  # noqa: E402
from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts import g3_mechanical_grinder as g3  # noqa: E402
from scripts import i1_candidate_universe as i1  # noqa: E402

J1A_CONTRACT = "j1a-data-readiness-v1"

# Frozen J0 section-9 benchmark geometry (no alternatives, no search).
BETA_ESTIMATION_RETURNS = 252
BETA_EMBARGO_SESSIONS = 20
# 252 daily returns ending at r_{i-21} need prices back to session i-273.
BETA_HISTORY_PREREQ = BETA_ESTIMATION_RETURNS + BETA_EMBARGO_SESSIONS + 1

ERA_START = i1.ERA_START
ERA_END = i1.ERA_END

# Fetch ranges mirror the Mission I substrate (equities) and extend the
# documented Treasury path through the same 2026-06-30 end so era-end
# anchors keep their forward observation (dates only; no outcome).
J1A_FETCH_START = g3.G3_FETCH_START
J1A_FETCH_END = g3.G3_FETCH_END
TREASURY_YEARS = tuple(range(2016, 2027))

NEW_ETF_TICKERS = ("SHY", "IAT", "KBE", "VFH")

CACHE_DIR = gsa.CACHE_DIR
G3_PRICE_DB = g3.G3_PRICE_DB
J1A_PRICE_DB = CACHE_DIR / "j1a_price_cache.db"
J1A_PRICE_META = CACHE_DIR / "j1a_price_meta.json"
J1A_TREASURY_CACHE = CACHE_DIR / "j1a_treasury.json"

REPORT_PATH = ROOT / "stats" / "J1A_DATA_READINESS.md"

# The J0 section-12.2 separation: the curve-shape observable is NOT a
# rates-panel member and never contributes to rates-role proxy agreement.
RATES_PANEL_MEASUREMENTS = ("2Y_CMT", "SHY")

# ---------------------------------------------------------------------------
# Frozen 12-cell manifest — traced verbatim from J0 section 13 (J1 table).
# ---------------------------------------------------------------------------

_ROLE_BANK = "balance_sheet_sensitive_second_order"
_ROLE_SECTOR = "broad_financial_sector"
_ROLE_RATES = "policy_rates_repricing"
_ROLE_CURVE = "curve_shape_contextual_layer"

FROZEN_MANIFEST: tuple[dict[str, Any], ...] = (
    {"cell": 1, "measurement": "KRE", "lens": "rolling_beta_ar",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "A instrument; B statistic",
     "source": "yahoo_chart (g3_price_cache.db)"},
    {"cell": 2, "measurement": "IAT", "lens": "rolling_beta_ar",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
    {"cell": 3, "measurement": "KBE", "lens": "rolling_beta_ar",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
    {"cell": 4, "measurement": "XLF", "lens": "rolling_beta_ar",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "A instrument; B statistic",
     "source": "yahoo_chart (g3_price_cache.db)"},
    {"cell": 5, "measurement": "VFH", "lens": "rolling_beta_ar",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
    {"cell": 6, "measurement": "IAT", "lens": "raw_return",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
    {"cell": 7, "measurement": "KBE", "lens": "raw_return",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
    {"cell": 8, "measurement": "XLF", "lens": "raw_return",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "A instrument; B statistic",
     "source": "yahoo_chart (g3_price_cache.db)"},
    {"cell": 9, "measurement": "VFH", "lens": "raw_return",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
    {"cell": 10, "measurement": "2Y_CMT", "lens": "raw_change",
     "role": _ROLE_RATES, "m_class": "M2",
     "evidence_class": "B statistic",
     "source": "treasury_daily_yield_curve_csv (j1a_treasury.json)"},
    {"cell": 11, "measurement": "2S10S_CMT", "lens": "raw_change",
     "role": _ROLE_CURVE, "m_class": "M2",
     "evidence_class": "B statistic (underlying series A as a state)",
     "source": "treasury_daily_yield_curve_csv (j1a_treasury.json)"},
    {"cell": 12, "measurement": "SHY", "lens": "raw_return",
     "role": _ROLE_RATES, "m_class": "M3",
     "evidence_class": "B instrument; B statistic",
     "source": "yahoo_chart (j1a_price_cache.db)"},
)


# ---------------------------------------------------------------------------
# Treasury path: persist the 2 Yr level via the existing documented source.
# ---------------------------------------------------------------------------


def parse_treasury_years(*, getter: Callable[..., bytes] = gsa._get,
                         years: Sequence[int] = TREASURY_YEARS,
                         start: str, end: str
                         ) -> tuple[dict[str, float], dict[str, float],
                                    dict[str, int]]:
    """Parse the official Treasury daily yield-curve CSVs.

    Returns ``(two_yr_level, spread_2s10s, duplicate_date_counts)``. Exactly
    the ``fetch_curve_2s10s`` source, URL shape, and date semantics; the
    difference is that the ``2 Yr`` level is now kept (J0 section 8). No
    interpolation, no forward-fill, no invented observation: a date absent
    from the source stays absent; an unparseable leg leaves that leg
    missing. Duplicate dates are explicit: identical repeats collapse to
    one observation and are counted; conflicting repeats fail loudly.
    """
    base = ("https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/daily-treasury-rates.csv/{y}/all"
            "?type=daily_treasury_yield_curve&field_tdr_date_value={y}"
            "&page&_format=csv")
    two_yr: dict[str, float] = {}
    spread: dict[str, float] = {}
    seen: dict[str, tuple[Optional[float], Optional[float]]] = {}
    duplicates: Counter = Counter()
    for y in years:
        raw = getter(base.format(y=y)).decode("utf-8", "replace")
        lines = raw.splitlines()
        if not lines:
            continue
        header = [h.strip().strip('"') for h in lines[0].split(",")]
        try:
            i2, i10 = header.index("2 Yr"), header.index("10 Yr")
            idate = header.index("Date")
        except ValueError as exc:
            raise RuntimeError(f"Treasury CSV header drifted for {y}: {exc}")
        for line in lines[1:]:
            cells = [c.strip().strip('"') for c in line.split(",")]
            if len(cells) <= max(i2, i10, idate):
                continue
            try:
                iso = gsa._mmddyyyy_to_iso(cells[idate])
            except (ValueError, IndexError):
                continue
            if not (start <= iso <= end):
                continue
            v2: Optional[float]
            v10: Optional[float]
            try:
                v2 = float(cells[i2])
            except (ValueError, IndexError):
                v2 = None
            try:
                v10 = float(cells[i10])
            except (ValueError, IndexError):
                v10 = None
            if iso in seen:
                duplicates[iso] += 1
                if seen[iso] != (v2, v10):
                    raise RuntimeError(
                        f"conflicting duplicate Treasury observation on "
                        f"{iso}: {seen[iso]} vs {(v2, v10)} - refusing")
                continue
            seen[iso] = (v2, v10)
            if v2 is not None:
                two_yr[iso] = v2
            if v2 is not None and v10 is not None:
                spread[iso] = v10 - v2
    dup = {d: n + 1 for d, n in duplicates.items()}
    return two_yr, spread, dup


def save_treasury_cache(two_yr: Mapping[str, float],
                        spread: Mapping[str, float],
                        duplicates: Mapping[str, int],
                        path: Path) -> None:
    """Persist both series in one gitignored cache file (source dates only)."""
    def _series_meta(series: Mapping[str, float], name: str) -> dict:
        dates = sorted(series)
        return {"series": name, "observations": len(series),
                "first": dates[0] if dates else None,
                "last": dates[-1] if dates else None}

    payload = {
        "meta": {
            "contract": J1A_CONTRACT,
            "source": "U.S. Treasury daily yield-curve CSVs",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "duplicate_dates": dict(sorted(duplicates.items())),
            "two_yr": _series_meta(two_yr, "2 Yr CMT level"),
            "spread_2s10s": _series_meta(
                spread, "10 Yr minus 2 Yr CMT spread"),
        },
        "series": {"two_yr": dict(two_yr),
                   "spread_2s10s": dict(spread)},
    }
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def load_treasury_cache(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def existing_spread_drift(spread: Mapping[str, float]) -> dict[str, Any]:
    """Compare the refetched spread with the tracked-path G2 cache overlap.

    Read-only integrity probe: on every overlapping date the two values
    must agree exactly (the series is effectively unrevised); disagreement
    is reported, never silently overwritten.
    """
    existing = gsa._load("curve_2s10s") or {}
    overlap = sorted(set(existing) & set(spread))
    mismatches = [d for d in overlap if existing[d] != spread[d]]
    return {"existing_observations": len(existing),
            "overlap": len(overlap), "mismatches": mismatches}


# ---------------------------------------------------------------------------
# Equity path: the existing Yahoo seam, new isolated cache DB.
# ---------------------------------------------------------------------------


def fetch_new_etfs(*, getter: Callable[..., bytes] = gsa._get
                   ) -> dict[str, tuple[dict[str, float], dict[str, float]]]:
    """Fetch SHY/IAT/KBE/VFH via the existing G3 Yahoo chart seam."""
    series: dict[str, tuple[dict[str, float], dict[str, float]]] = {}
    for ticker in NEW_ETF_TICKERS:
        raw, adj, _meta = g3.fetch_yahoo_ohlc(
            ticker, start=J1A_FETCH_START, end=J1A_FETCH_END, getter=getter)
        series[ticker] = (raw, adj)
    return series


def build_j1a_price_db(path: Path, series: Mapping[str, tuple],
                       meta_path: Optional[Path] = None,
                       *, fetched_at: str) -> dict[str, Any]:
    """Write the isolated J1A ETF cache via the existing G3 DB builder."""
    g3.build_price_db(path, series, fetched_at=fetched_at)
    counts = {t: {"raw": len(r), "adjusted": len(a)}
              for t, (r, a) in series.items()}
    meta = {"contract": J1A_CONTRACT, "retrieved_at": fetched_at,
            "tickers": counts, "start": J1A_FETCH_START,
            "end": J1A_FETCH_END,
            "source": "Yahoo public chart endpoint "
                      "(raw close + adjusted close)"}
    if meta_path is not None:
        Path(meta_path).write_text(json.dumps(meta, sort_keys=True),
                                   encoding="utf-8")
    return meta


def pair_frame(asset: str, asset_db: Path, bench: str, bench_db: Path
               ) -> tuple[list[str], str, int]:
    """Matched-basis joint session frame for (asset, benchmark).

    Adjusted/adjusted preferred (F3); the disclosed matched raw/raw
    fallback is COUNTED (sessions raw-joint but not adjusted-joint), never
    silently joined; a cross-basis pair never exists by construction.
    """
    adj = (i1._adjusted_dates(asset, asset_db)
           & i1._adjusted_dates(bench, bench_db))
    raw = (i1._raw_dates(asset, asset_db)
           & i1._raw_dates(bench, bench_db))
    return sorted(adj), "adjusted", len(raw - adj)


def single_frame(ticker: str, db_path: Path) -> tuple[list[str], str, int]:
    """Matched-basis session frame for a single-asset lens."""
    adj = i1._adjusted_dates(ticker, db_path)
    raw = i1._raw_dates(ticker, db_path)
    return sorted(adj), "adjusted", len(raw - adj)


# ---------------------------------------------------------------------------
# Frozen readiness geometry (identical for event and reference anchors).
# ---------------------------------------------------------------------------


def beta_readiness(frame: Sequence[str], idx: int) -> dict[str, Any]:
    """J0 section-9 rolling-beta geometry at one anchor (dates only).

    Estimation returns are r_j for j in {i-272, ..., i-21} (exactly 252),
    needing prices back to session i-273; the embargo is the 20 sessions
    i-20 .. i-1; the response window is [i, i+1]. No return value is
    computed or returned here - identities and counts only.
    """
    n = len(frame)
    if idx < BETA_HISTORY_PREREQ:
        return {"ready": False,
                "failure_reason": "insufficient_history_252_20"}
    if idx + 1 > n - 1:
        return {"ready": False, "failure_reason": "no_forward_session"}
    if not esv._is_contiguous(list(frame[idx:idx + 2])):
        return {"ready": False, "failure_reason": "response_window_gap"}
    return {
        "ready": True,
        "failure_reason": None,
        "n_estimation_returns": BETA_ESTIMATION_RETURNS,
        "estimation_first_session": frame[idx - BETA_HISTORY_PREREQ],
        "estimation_last_session": frame[idx - BETA_EMBARGO_SESSIONS - 1],
        "embargo_sessions": BETA_EMBARGO_SESSIONS,
        "embargo_first_session": frame[idx - BETA_EMBARGO_SESSIONS],
        "embargo_last_session": frame[idx - 1],
    }


def raw_readiness(frame: Sequence[str], idx: int) -> dict[str, Any]:
    """Raw-return lens geometry: forward session + response-window guard."""
    n = len(frame)
    if idx + 1 > n - 1:
        return {"ready": False, "failure_reason": "no_forward_session"}
    if not esv._is_contiguous(list(frame[idx:idx + 2])):
        return {"ready": False, "failure_reason": "response_window_gap"}
    return {"ready": True, "failure_reason": None}


def rates_readiness(frame: Sequence[str], idx: int) -> dict[str, Any]:
    """Rates raw-change lens geometry on the series' own calendar.

    Forward observation only: the shipped equity interior-gap guard does
    not apply to official yield series (J0 section 10, "where the shipped
    engine applies"); missing observations simply gate out via absence.
    """
    n = len(frame)
    if idx + 1 > n - 1:
        return {"ready": False, "failure_reason": "no_forward_session"}
    return {"ready": True, "failure_reason": None}


_LENS_READINESS = {
    "rolling_beta_ar": beta_readiness,
    "raw_return": raw_readiness,
    "raw_change": rates_readiness,
}


def anchor_readiness(frame: Sequence[str], idx: int, lens: str
                     ) -> dict[str, Any]:
    """One shared measurement boundary; membership is metadata elsewhere."""
    return _LENS_READINESS[lens](frame, idx)


def ols_alpha_beta(x: Sequence[float], y: Sequence[float]
                   ) -> tuple[float, float]:
    """OLS with intercept on exactly the frozen 252 paired observations."""
    if len(x) != BETA_ESTIMATION_RETURNS or len(y) != BETA_ESTIMATION_RETURNS:
        raise ValueError(
            f"frozen model requires exactly {BETA_ESTIMATION_RETURNS} "
            f"paired observations, got {len(x)}/{len(y)}")
    n = float(len(x))
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((v - mx) * (v - mx) for v in x)
    if sxx == 0.0:
        raise ValueError("degenerate benchmark series (zero variance)")
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    beta = sxy / sxx
    alpha = my - beta * mx
    return alpha, beta


# ---------------------------------------------------------------------------
# Cell funnels (symmetric: one gate function feeds both sides).
# ---------------------------------------------------------------------------


def build_cell_funnel_from_frame(*, cell: Mapping[str, Any],
                                 frame: Sequence[str],
                                 event_dates: Sequence[str],
                                 coverage: tuple[Optional[str], Optional[str]],
                                 basis: str, raw_only: int
                                 ) -> dict[str, Any]:
    """Event and ordinary-reference availability funnel for one cell.

    Both sides call the identical ``anchor_readiness``; the reference side
    additionally applies the era bounds and the frozen exclusion (buffer =
    window span = 1 session against the 65-event frame anchors). Counts
    and identities only - never a close, return, or response value.
    """
    lens = str(cell["lens"])
    frame = list(frame)

    # --- event side -------------------------------------------------------
    event_anchor_idx: dict[str, Optional[int]] = {
        d: esv._last_index_le(frame, d) for d in event_dates}
    ev_ready_years: Counter = Counter()
    ev_unavailable: list[tuple[str, str]] = []
    ev_ready = 0
    for d in sorted(event_anchor_idx):
        idx = event_anchor_idx[d]
        if idx is None:
            ev_unavailable.append((d, "date_precedes_frame"))
            continue
        r = anchor_readiness(frame, idx, lens)
        if r["ready"]:
            ev_ready += 1
            ev_ready_years[frame[idx][:4]] += 1
        else:
            ev_unavailable.append((d, str(r["failure_reason"])))
    ev_failures: Counter = Counter(reason for _, reason in ev_unavailable)

    # --- reference side (same gate, plus era + exclusion) ------------------
    anchor_indices = sorted({i for i in event_anchor_idx.values()
                             if i is not None})
    era = [i for i, d in enumerate(frame) if ERA_START <= d <= ERA_END]
    ref_failures: Counter = Counter()
    survivors: list[int] = []
    for idx in era:
        r = anchor_readiness(frame, idx, lens)
        if r["ready"]:
            survivors.append(idx)
        else:
            ref_failures[str(r["failure_reason"])] += 1
    excluded = [i for i in survivors
                if any(abs(i - e) <= 1 for e in anchor_indices)]
    ready_indices = [i for i in survivors
                     if not any(abs(i - e) <= 1 for e in anchor_indices)]
    ref_ready_years: Counter = Counter(frame[i][:4] for i in ready_indices)

    return {
        "cell": dict(cell),
        "coverage_first": coverage[0],
        "coverage_last": coverage[1],
        "basis": basis,
        "raw_only_sessions": raw_only,
        "frame_sessions": len(frame),
        "event": {
            "attempted": len(event_dates),
            "ready": ev_ready,
            "unavailable": ev_unavailable,
            "failure_counts": dict(sorted(ev_failures.items())),
            "ready_by_year": dict(sorted(ev_ready_years.items())),
        },
        "reference": {
            "attempted": len(era),
            "ready": len(ready_indices),
            "ready_indices": ready_indices,
            "excluded_event_proximity": len(excluded),
            "failure_counts": dict(sorted(ref_failures.items())),
            "ready_by_year": dict(sorted(ref_ready_years.items())),
        },
        "embargo_confirmed": lens != "rolling_beta_ar" or
        BETA_EMBARGO_SESSIONS == 20,
    }


def _frame_for_cell(cell: Mapping[str, Any], *, g3_db: Path, j1a_db: Path,
                    treasury: Mapping[str, Any]
                    ) -> tuple[list[str], str, int]:
    m = str(cell["measurement"])
    lens = str(cell["lens"])
    g3_tickers = {"KRE", "XLF", "SPY"}
    if lens == "rolling_beta_ar":
        adb = g3_db if m in g3_tickers else j1a_db
        return pair_frame(m, adb, "SPY", g3_db)
    if lens == "raw_return":
        adb = g3_db if m in g3_tickers else j1a_db
        return single_frame(m, adb)
    key = "two_yr" if m == "2Y_CMT" else "spread_2s10s"
    dates = sorted(treasury["series"][key])
    return dates, "official_level_percentage_points", 0


def build_readiness(*, g3_db: Path = G3_PRICE_DB,
                    j1a_db: Path = J1A_PRICE_DB,
                    treasury_path: Path = J1A_TREASURY_CACHE
                    ) -> dict[str, Any]:
    """Build all 12 outcome-blind cell funnels from the local caches."""
    for p in (g3_db, j1a_db, treasury_path):
        if not Path(p).exists():
            raise RuntimeError(f"required local cache missing: {p} - "
                               "run --fetch first (fail-loud, no fallback)")
    treasury = load_treasury_cache(Path(treasury_path))
    event_dates = i1.parse_fomc_frame_dates()
    if len(event_dates) != 65:
        raise RuntimeError(
            f"FOMC frame drifted: {len(event_dates)} != 65 - refusing")
    funnels: list[dict[str, Any]] = []
    for cell in FROZEN_MANIFEST:
        frame, basis, raw_only = _frame_for_cell(
            cell, g3_db=Path(g3_db), j1a_db=Path(j1a_db), treasury=treasury)
        coverage = (frame[0] if frame else None,
                    frame[-1] if frame else None)
        funnels.append(build_cell_funnel_from_frame(
            cell=cell, frame=frame, event_dates=event_dates,
            coverage=coverage, basis=basis, raw_only=raw_only))
    if len(funnels) != 12:
        raise RuntimeError("cell reconciliation failed: expected 12 funnels")
    provenance = {
        "contract": J1A_CONTRACT,
        "fomc_events": 65,
        "g3_meta": json.loads((CACHE_DIR / "g3_price_meta.json")
                              .read_text(encoding="utf-8")),
        "j1a_meta": json.loads(Path(J1A_PRICE_META)
                               .read_text(encoding="utf-8")),
        "treasury_meta": treasury["meta"],
        "spread_drift": existing_spread_drift(treasury["series"]
                                              ["spread_2s10s"]),
    }
    return {"funnels": funnels, "provenance": provenance}


# ---------------------------------------------------------------------------
# Deterministic outcome-blind report.
# ---------------------------------------------------------------------------


def _year_table(mapping: Mapping[str, int]) -> str:
    if not mapping:
        return "(none)"
    return ", ".join(f"{y}:{n}" for y, n in sorted(mapping.items()))


def render_report(funnels: Sequence[Mapping[str, Any]],
                  provenance: Mapping[str, Any]) -> str:
    """Deterministic markdown; counts, dates, and reasons only."""
    L: list[str] = []
    L.append("# J1A data readiness - outcome-blind symmetric substrate "
             "(Mission J)")
    L.append("")
    L.append(f"Contract: `{J1A_CONTRACT}`, executing the locked j0-v1 "
             "constitution over the 12 frozen J1 state-bearing cells. This "
             "report contains availability geometry ONLY: no event-window "
             "response value, no MEMP, no placement calibration, no node "
             "or edge state, and no proxy ranking appears here or in any "
             "J1A output. Event and ordinary-reference anchors were gated "
             "by the identical readiness functions (membership is "
             "metadata, not mathematics).")
    L.append("")
    L.append("## Frozen manifest and headline funnel (12 cells, J0 order)")
    L.append("")
    L.append("| # | measurement | lens | role | M | events ready / 65 | "
             "reference ready / era attempted | excluded (+-1) | "
             "coverage first..last |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for f in funnels:
        c = f["cell"]
        ev, ref = f["event"], f["reference"]
        L.append(
            f"| {c['cell']} | {c['measurement']} | {c['lens']} | "
            f"{c['role']} | {c['m_class']} | {ev['ready']} / "
            f"{ev['attempted']} | {ref['ready']} / {ref['attempted']} | "
            f"{ref['excluded_event_proximity']} | "
            f"{f['coverage_first']} .. {f['coverage_last']} |")
    L.append("")
    L.append("## Per-cell detail")
    for f in funnels:
        c = f["cell"]
        ev, ref = f["event"], f["reference"]
        L.append("")
        L.append(f"### Cell {c['cell']} - {c['measurement']} "
                 f"({c['lens']})")
        L.append("")
        L.append(f"- role: {c['role']}; M-class: {c['m_class']}; "
                 f"evidence class: {c['evidence_class']}")
        L.append(f"- source: {c['source']}; basis: {f['basis']}; "
                 f"raw-only (disclosed fallback) sessions: "
                 f"{f['raw_only_sessions']}")
        L.append(f"- frame sessions: {f['frame_sessions']}; coverage "
                 f"{f['coverage_first']} .. {f['coverage_last']}")
        L.append(f"- events: attempted {ev['attempted']}, ready "
                 f"{ev['ready']}, unavailable {len(ev['unavailable'])}")
        L.append(f"- event ready-by-year: {_year_table(ev['ready_by_year'])}")
        if ev["unavailable"]:
            for d, reason in ev["unavailable"]:
                L.append(f"  - unavailable event {d}: {reason}")
        L.append(f"- event failure counts: "
                 f"{json.dumps(ev['failure_counts'], sort_keys=True)}")
        L.append(f"- reference: era attempted {ref['attempted']}, ready "
                 f"{ref['ready']}, excluded by event proximity (+-1) "
                 f"{ref['excluded_event_proximity']}")
        L.append(f"- reference failure counts: "
                 f"{json.dumps(ref['failure_counts'], sort_keys=True)}")
        L.append(f"- reference ready-by-year: "
                 f"{_year_table(ref['ready_by_year'])}")
        if c["lens"] == "rolling_beta_ar":
            hist = (ev["failure_counts"].get(
                "insufficient_history_252_20", 0),
                ref["failure_counts"].get("insufficient_history_252_20", 0))
            gap = (ev["failure_counts"].get("response_window_gap", 0),
                   ref["failure_counts"].get("response_window_gap", 0))
            L.append(f"- rolling-beta gates: anchors failing 252/20 "
                     f"history: events {hist[0]}, reference {hist[1]}; "
                     f"failing response-window alignment: events {gap[0]}, "
                     f"reference {gap[1]}; failing basis compatibility: 0 "
                     f"(cross-basis pairs are structurally impossible; "
                     f"raw-only sessions disclosed above)")
            L.append(f"- embargo: exactly {BETA_EMBARGO_SESSIONS} completed "
                     f"aligned sessions immediately before every anchor, "
                     f"estimation strictly precedes it "
                     f"(confirmed: {f['embargo_confirmed']})")
    L.append("")
    L.append("## Provenance (dates and counts only)")
    L.append("")
    L.append("```json")
    L.append(json.dumps(provenance, indent=1, sort_keys=True))
    L.append("```")
    L.append("")
    L.append("## Boundary")
    L.append("")
    L.append("Not computed here (they belong to J1B under the frozen "
             "constitution): event responses, ordinary-reference "
             "responses, event percentiles, MEMPs, placement calibration, "
             "node states, edge states, and any proxy comparison. The "
             "section-11 feasibility rule (`insufficient subset under the "
             "frozen procedure`) is evaluated in J1B against these "
             "funnels; no numeric floor exists.")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Frozen-input snapshot (pre-outcome input immutability; j1a freeze).
#
# Repeated Yahoo fetches during J1A preserved ticker/date keys and raw
# closes exactly but showed tiny adjusted-close refetch drift (max relative
# difference ~1.5e-06). J1B consumes the frozen adjusted/adjusted-preferred
# basis, so J1 pins the exact local snapshot bytes below rather than
# treating a future provider refetch as byte-identical evidence. This is a
# reproducibility statement, not a provider-quality or economic-magnitude
# claim.
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402

FROZEN_MANIFEST_PATH = ROOT / "stats" / "J1A_FROZEN_INPUTS.md"

J1B_INPUT_GATE = (
    "J1B must call require_frozen_inputs() and receive success before "
    "computing any response value. On any mismatch: stop, report the "
    "mismatched file and invariant, do not refetch automatically, do not "
    "recompute outcomes.")

_ETF_ROWS = {
    (t, basis): (2385, "2017-01-03", "2026-06-30")
    for t in NEW_ETF_TICKERS for basis in (0, 1)
}

FROZEN_INPUTS: dict[str, dict[str, Any]] = {
    "j1a_price_cache.db": {
        "sha256": "b735c227d8155816045eca4bbfc83b361caa644822"
                  "52182ed4b2c227794eac28",
        "bytes": 1990656,
        "kind": "sqlite",
        "role": "J1 new-ETF price substrate (SHY/IAT/KBE/VFH, raw + "
                "adjusted daily closes)",
        "source": "Yahoo public chart endpoint via the existing G3 seam",
        "provenance": "fetched 2026-07-06T19:37:20.498248+00:00 by "
                      "scripts/j1a_data_readiness.py --fetch (temp-proofed "
                      "first; zero-cost)",
        "j1b_may_mutate": False,
        "tables": ["price_cache"],
        "providers": ["yahoo_chart"],
        "rows": _ETF_ROWS,
    },
    "j1a_price_meta.json": {
        "sha256": "e4a09b00a72a71f0f2659edcca7dc6df8062011e21"
                  "0699f798095248c36b2b89",
        "bytes": 376,
        "kind": "opaque",
        "role": "J1 ETF cache provenance metadata",
        "source": "written beside the cache by the same --fetch",
        "provenance": "fetched 2026-07-06T19:37:20.498248+00:00",
        "j1b_may_mutate": False,
    },
    "j1a_treasury.json": {
        "sha256": "b1df6fa21dfffb281c2f363e439609457a5c2765f8"
                  "73420f8dcac91ca8c529e7",
        "bytes": 127924,
        "kind": "treasury",
        "role": "J1 rates substrate: 2 Yr CMT level and 2s10s CMT spread",
        "source": "official U.S. Treasury daily yield-curve CSVs "
                  "(existing documented path)",
        "provenance": "fetched 2026-07-06T19:37:40.054780+00:00 by "
                      "--fetch; refetched spread matched the tracked-path "
                      "G2 cache on all 2,396 overlapping dates",
        "j1b_may_mutate": False,
        "series": {"two_yr": (2520, "2016-06-01", "2026-06-30"),
                   "spread_2s10s": (2520, "2016-06-01", "2026-06-30")},
        "duplicate_dates": {},
    },
    "g3_price_cache.db": {
        "sha256": "a5bb09f87fa6566588baa6638119ce7b0b349d0214"
                  "3c72415b49d426b14c2754",
        "bytes": 2502656,
        "kind": "opaque",
        "role": "inherited Mission I substrate (KRE/XLF/SPY legs of the "
                "J1 frames)",
        "source": "Yahoo public chart endpoint (G3 fetch)",
        "provenance": "inherited pin: this SHA-256 is already documented "
                      "in stats/G3_MECHANICAL_ELIGIBILITY.md section 7; "
                      "no new freeze decision is made here",
        "j1b_may_mutate": False,
    },
}


def _verify_sqlite_structure(path: Path, exp: Mapping[str, Any],
                             failures: list[str]) -> None:
    basis_name = {0: "raw", 1: "adjusted"}
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            tables = sorted(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"))
            if tables != sorted(exp["tables"]):
                failures.append(f"{path.name}: tables {tables} != "
                                f"{sorted(exp['tables'])}")
            providers = sorted(r[0] for r in conn.execute(
                "SELECT DISTINCT source_provider FROM price_cache"))
            if providers != sorted(exp["providers"]):
                failures.append(f"{path.name}: providers {providers} != "
                                f"{sorted(exp['providers'])}")
            got: dict[tuple[str, int], tuple] = {}
            for t, adj, n, lo, hi in conn.execute(
                    "SELECT ticker, auto_adjust, COUNT(*), MIN(date), "
                    "MAX(date) FROM price_cache GROUP BY ticker, "
                    "auto_adjust"):
                got[(t, adj)] = (n, lo, hi)
            for key, want in exp["rows"].items():
                t, adj = key
                if got.get(key) != tuple(want):
                    failures.append(
                        f"{path.name}: {t} {basis_name[adj]} rows "
                        f"{got.get(key)} != expected {tuple(want)} "
                        f"(count {want[0]})")
            for key in got:
                if key not in exp["rows"]:
                    failures.append(f"{path.name}: unexpected series "
                                    f"{key[0]} {basis_name[key[1]]}")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        failures.append(f"{path.name}: unreadable sqlite ({exc})")


def _verify_treasury_structure(path: Path, exp: Mapping[str, Any],
                               failures: list[str]) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        failures.append(f"{path.name}: unreadable json ({exc})")
        return
    series = payload.get("series", {})
    for name, want in exp["series"].items():
        data = series.get(name, {})
        dates = sorted(data)
        got = (len(data), dates[0] if dates else None,
               dates[-1] if dates else None)
        if got != tuple(want):
            failures.append(f"{path.name}: {name} observations/bounds "
                            f"{got} != expected {tuple(want)} "
                            f"(count {want[0]})")
    dup = payload.get("meta", {}).get("duplicate_dates")
    if dup != exp["duplicate_dates"]:
        failures.append(f"{path.name}: duplicate_dates {dup} != "
                        f"{exp['duplicate_dates']}")


def verify_frozen_inputs(cache_dir: Path = CACHE_DIR,
                         expectations: Mapping[str, Mapping[str, Any]]
                         = FROZEN_INPUTS) -> list[str]:
    """Read-only verification of the exact frozen J1 input snapshot.

    Collects EVERY mismatch (no short-circuit) and never fetches, repairs,
    rewrites, normalizes, or updates anything. Empty list means the local
    snapshot is byte- and structure-identical to the freeze.
    """
    failures: list[str] = []
    for name, exp in expectations.items():
        p = Path(cache_dir) / name
        if not p.exists():
            failures.append(f"{name}: missing from {cache_dir}")
            continue
        size = p.stat().st_size
        if size != exp["bytes"]:
            failures.append(f"{name}: size {size} bytes != frozen "
                            f"{exp['bytes']} bytes")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != exp["sha256"]:
            failures.append(f"{name}: sha256 {digest} != frozen "
                            f"{exp['sha256']}")
        if exp.get("kind") == "sqlite":
            _verify_sqlite_structure(p, exp, failures)
        elif exp.get("kind") == "treasury":
            _verify_treasury_structure(p, exp, failures)
    return failures


def require_frozen_inputs(cache_dir: Path = CACHE_DIR) -> None:
    """The J1B gate: raise (stop) on any frozen-input mismatch."""
    failures = verify_frozen_inputs(cache_dir)
    if failures:
        raise RuntimeError(
            "frozen J1 inputs failed verification - stopping without "
            "refetch or outcome computation:\n" + "\n".join(failures))


def render_frozen_manifest() -> str:
    """Deterministic tracked manifest of the frozen J1 input snapshot."""
    basis_name = {0: "raw", 1: "adjusted"}
    L: list[str] = []
    L.append("# J1A frozen inputs - the exact pre-outcome data snapshot "
             "(Mission J)")
    L.append("")
    L.append(f"Contract: `{J1A_CONTRACT}` input freeze. The gitignored "
             "local files below are the EXACT bytes the J1B comparison "
             "must consume; they were pinned before any J1 outcome was "
             "computed or inspected. They are local inputs, not tracked "
             "artifacts; this manifest and the machine verifier "
             "(`scripts/j1a_data_readiness.py::verify_frozen_inputs`) are "
             "the tracked record.")
    L.append("")
    L.append("## Provider-drift note (why bytes are pinned)")
    L.append("")
    L.append("During J1A, repeated fetches from the zero-cost provider "
             "preserved ticker/date keys and raw closes exactly, while "
             "adjusted closes exhibited tiny refetch drift (max relative "
             "difference about 1.5e-06). J1B uses the frozen "
             "adjusted/adjusted-preferred basis, so Mission J consumes "
             "this exact frozen local snapshot rather than treating a "
             "future provider refetch as byte-identical evidence. This is "
             "a reproducibility discipline; it is not a provider-quality "
             "claim, and the drift magnitude is not read as economically "
             "meaningful.")
    L.append("")
    L.append("## J1B gate (frozen rule)")
    L.append("")
    L.append(f"> {J1B_INPUT_GATE}")
    L.append("")
    L.append("## Frozen files")
    L.append("")
    L.append("| file (g_state_cache/) | sha256 | bytes | role | "
             "J1B may mutate |")
    L.append("|---|---|---|---|---|")
    for name in sorted(FROZEN_INPUTS):
        exp = FROZEN_INPUTS[name]
        L.append(f"| `{name}` | `{exp['sha256']}` | {exp['bytes']} | "
                 f"{exp['role']} | no |")
    L.append("")
    for name in sorted(FROZEN_INPUTS):
        exp = FROZEN_INPUTS[name]
        L.append(f"### `g_state_cache/{name}`")
        L.append("")
        L.append(f"- sha256: `{exp['sha256']}`; size: {exp['bytes']} bytes")
        L.append(f"- source: {exp['source']}")
        L.append(f"- role: {exp['role']}")
        L.append(f"- provenance: {exp['provenance']}")
        L.append("- J1B may mutate: no (read-only input)")
        if exp.get("kind") == "sqlite":
            L.append(f"- tables: {', '.join(exp['tables'])}; provider "
                     f"identity: {', '.join(exp['providers'])}")
            for (t, adj) in sorted(exp["rows"]):
                n, lo, hi = exp["rows"][(t, adj)]
                L.append(f"- {t} {basis_name[adj]}: {n} rows, "
                         f"{lo} .. {hi}")
        if exp.get("kind") == "treasury":
            for sname in sorted(exp["series"]):
                n, lo, hi = exp["series"][sname]
                L.append(f"- {sname}: {n} observations, {lo} .. {hi}")
            L.append(f"- duplicate source dates: "
                     f"{len(exp['duplicate_dates'])}")
            L.append("- source identity: official U.S. Treasury daily "
                     "yield-curve CSV distribution (the existing "
                     "documented path; same parser columns as the "
                     "tracked 2s10s series)")
        L.append("")
    L.append("## Boundary")
    L.append("")
    L.append("The verifier is read-only: it never fetches, repairs, "
             "rewrites, normalizes, or updates metadata. No response "
             "value, MEMP, calibration, node state, or edge state exists "
             "in this freeze or its verifier.")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Probes and CLI (zero-cost sources only; no paid call exists in this path).
# ---------------------------------------------------------------------------


def probe_sources() -> dict[str, Any]:  # pragma: no cover - network probe
    out: dict[str, Any] = {}
    try:
        two_yr, spread, dup = parse_treasury_years(
            years=(2024,), start="2024-01-01", end="2024-01-31")
        out["treasury"] = {"ok": bool(two_yr), "two_yr_obs": len(two_yr),
                           "spread_obs": len(spread), "duplicates": dup}
    except Exception as exc:  # noqa: BLE001 - bounded evidence capture
        out["treasury"] = {"ok": False,
                           "error": f"{type(exc).__name__}: {exc}"}
    for t in NEW_ETF_TICKERS:
        out[t] = g3.probe_source_health(t)
    return out


def run_fetch(*, db_path: Path = J1A_PRICE_DB,
              meta_path: Path = J1A_PRICE_META,
              treasury_path: Path = J1A_TREASURY_CACHE
              ) -> dict[str, Any]:  # pragma: no cover - network fetch
    """Acquire the J1A substrate into the isolated cache boundary only."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    two_yr, spread, dup = parse_treasury_years(
        start="2016-06-01", end=J1A_FETCH_END)
    save_treasury_cache(two_yr, spread, dup, Path(treasury_path))
    series = fetch_new_etfs()
    meta = build_j1a_price_db(Path(db_path), series, Path(meta_path),
                              fetched_at=fetched_at)
    return {"treasury": {"two_yr": len(two_yr), "spread": len(spread),
                         "duplicates": dup},
            "etfs": meta["tickers"]}


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe-sources", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--dest", default=None,
                    help="alternate cache directory (temp-proof runs)")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--freeze", action="store_true",
                    help="verify the frozen inputs and write the tracked "
                         "freeze manifest")
    args = ap.parse_args(argv)
    if args.probe_sources:
        sys.stdout.buffer.write(json.dumps(
            probe_sources(), indent=1, sort_keys=True).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        return 0
    if args.fetch:
        dest = Path(args.dest) if args.dest else CACHE_DIR
        dest.mkdir(exist_ok=True)
        summary = run_fetch(db_path=dest / J1A_PRICE_DB.name,
                            meta_path=dest / J1A_PRICE_META.name,
                            treasury_path=dest / J1A_TREASURY_CACHE.name)
        sys.stdout.buffer.write(json.dumps(
            summary, indent=1, sort_keys=True).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        return 0
    if args.freeze:
        require_frozen_inputs()
        FROZEN_MANIFEST_PATH.write_text(render_frozen_manifest(),
                                        encoding="utf-8")
        sys.stdout.buffer.write(
            f"verified frozen inputs; wrote {FROZEN_MANIFEST_PATH}\n"
            .encode("utf-8"))
        return 0
    if args.emit:
        readiness = build_readiness()
        report = render_report(readiness["funnels"],
                               readiness["provenance"])
        REPORT_PATH.write_text(report, encoding="utf-8")
        sys.stdout.buffer.write(
            f"wrote {REPORT_PATH}\n".encode("utf-8"))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

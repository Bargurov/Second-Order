"""G6A - execution of the frozen G4 comparison manifest.

Mission G, protocol g0-v1, readout version g6a-frozen-manifest-readout-v1.

Executes the SIXTEEN manifest entries frozen at G4 - exactly as written -
over the 97 promoted `g_historical_evidence` rows, and renders the first
complete outcome-visible evidence surface. Read-only everywhere: no DB
mutation, no price fetch, no candidate selection.

Authority and bans: the frozen G4 manifest is the contract. This module
adds no axis, drops no axis, changes no tag, denominator, ticker, horizon,
or metric, never pools FOMC and OPEC, never conditions on the G3B
mechanism overlay, and never selects representative cases. Outcomes come
from the SHIPPED event-study gate (`event_study_validation
.build_event_study_validation`) under the frozen `g3-transmission-map-v1`
lenses and the canonical adjusted-preferred basis - there is no second
event-study implementation here. Exactly four metrics (absolute asset
return, SPY-relative AR, sector-relative AR, SAR) at the three shipped
horizons (1d, 5d, 20d); the gate's CAR field is deliberately not
extracted (spec section 4: no new metric, no SCAR).

Association is Spearman rank correlation ONLY - descriptive, tie-aware,
no p-value, no confidence interval, no significance label, no Pearson, no
regression, no binning of continuous axes. The frozen structural floor
(MIN_CELL_UNIQUE_DATES = 11, reused from G4, a support floor and not a
power claim) marks thin cells while keeping them fully visible.

Usage:

    python scripts/g6_frozen_manifest_readout.py --emit   # tracked report
    python scripts/g6_frozen_manifest_readout.py --json   # full structure
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import event_study_validation as esv  # noqa: E402
from scripts import g4_structural_freeze as g4  # noqa: E402
from scripts.g3_mechanical_grinder import (  # noqa: E402
    G3_PRICE_DB, TRANSMISSION_MAP, _basis_label)
from scripts.g5_promotion import G_COLUMNS as PROMOTED_COLUMNS  # noqa: E402
from scripts.g5_promotion import GTABLE, LIVE_DB  # noqa: E402

READOUT_VERSION = "g6a-frozen-manifest-readout-v1"
REPORT_PATH = ROOT / "stats" / "G6_FROZEN_MANIFEST_READOUT.md"
G4_REPORT_PATH = ROOT / "stats" / "G4_STRUCTURAL_FREEZE.md"

# The shipped horizons, taken FROM the shipped machinery (identity, not a
# re-declaration); G6A fails at import if the engine ever drifts.
HORIZONS: tuple[int, ...] = tuple(esv.HORIZONS)
if HORIZONS != (1, 5, 20):  # pragma: no cover - drift guard
    raise RuntimeError(f"shipped horizons drifted: {HORIZONS}")

METRICS = ("absolute_asset_return", "spy_relative_ar",
           "sector_relative_ar", "sar")

CONTINUOUS_AXES = ("fed_policy_path", "vix_level_percentile",
                   "spy_trend_ma200", "curve_2s10s", "credit_hy_oas")

_STATE_COLUMN = {
    "fed_policy_path": "state_fed_policy_path",
    "vix_level_percentile": "state_vix_level_percentile",
    "spy_trend_ma200": "state_spy_trend_ma200",
    "curve_2s10s": "state_curve_2s10s",
    "credit_hy_oas": "state_credit_hy_oas",
}

_TAG_AXES = {
    "fed_policy_path": ("tag_fed_policy_path",
                        ("easing", "hold", "tightening")),
    "spy_trend_ma200": ("tag_spy_trend_ma200", ("below_ma", "above_ma")),
    "curve_2s10s": ("tag_curve_2s10s", ("inverted", "non_inverted")),
}

# Frozen structural support floor - reused from G4, never redefined.
MIN_CELL_UNIQUE_DATES = g4.MIN_CELL_UNIQUE_DATES

_LANE_FAMILY = {"frame_complete_historical": "fomc",
                "designed_contrast": "opec"}


# ---------------------------------------------------------------------------
# Deterministic descriptive statistics (pure)
# ---------------------------------------------------------------------------


def five_number_summary(values: Sequence[float]) -> dict[str, float]:
    """min / p25 / median / p75 / max with the documented deterministic
    method: statistics.quantiles(..., n=4, method='inclusive')."""
    vals = sorted(float(v) for v in values)
    if not vals:
        raise ValueError("empty sample")
    if len(vals) == 1:
        v = vals[0]
        return {"min": v, "p25": v, "median": v, "p75": v, "max": v}
    q1, q2, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return {"min": vals[0], "p25": q1, "median": q2, "p75": q3,
            "max": vals[-1]}


def sign_counts(values: Sequence[float]) -> dict[str, int]:
    return {"positive": sum(1 for v in values if v > 0),
            "zero": sum(1 for v in values if v == 0),
            "negative": sum(1 for v in values if v < 0)}


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while (j + 1 < len(order)
               and values[order[j + 1]] == values[order[i]]):
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rho(xs: Sequence[float],
                 ys: Sequence[float]) -> Optional[float]:
    """Tie-aware Spearman: Pearson correlation of average ranks.
    Descriptive only - no p-value, no CI, no significance label.
    None when n < 2 or either side has zero rank variance."""
    if len(xs) != len(ys):
        raise ValueError("length mismatch")
    if len(xs) < 2:
        return None
    rx, ry = _average_ranks(xs), _average_ranks(ys)
    mx = statistics.fmean(rx)
    my = statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


# ---------------------------------------------------------------------------
# Promoted universe (read-only)
# ---------------------------------------------------------------------------


def load_promoted_rows(db_path: Path | str = LIVE_DB) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            f"SELECT {', '.join(PROMOTED_COLUMNS)} FROM {GTABLE} "
            "ORDER BY event_date, candidate_id")
        return [dict(zip(PROMOTED_COLUMNS, row)) for row in cur.fetchall()]
    finally:
        con.close()


def reconcile_universe(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    by_lane: dict[str, int] = {}
    for r in rows:
        by_lane[r["denominator_ledger"]] = by_lane.get(
            r["denominator_ledger"], 0) + 1
    recon = {
        "frame_complete_historical": by_lane.get(
            "frame_complete_historical", 0),
        "designed_contrast": by_lane.get("designed_contrast", 0),
        "total": len(rows),
        "unique_candidate_ids": len({r["candidate_id"] for r in rows}),
        "unique_event_dates": len({r["event_date"] for r in rows}),
    }
    failures = []
    if recon["frame_complete_historical"] != 65:
        failures.append("frame != 65")
    if recon["designed_contrast"] != 32:
        failures.append("designed != 32")
    if recon["total"] != 97 or recon["unique_candidate_ids"] != 97 \
            or recon["unique_event_dates"] != 97:
        failures.append("total/unique != 97")
    versions = {r["mapping_version"] for r in rows} | {
        r["freeze_version"] for r in rows}
    if versions != {"g3-transmission-map-v1", "g4-structural-freeze-v1"}:
        failures.append(f"version drift {sorted(versions)}")
    if failures:
        raise ValueError("promoted-universe drift: " + "; ".join(failures))
    return recon


# ---------------------------------------------------------------------------
# Manifest derivation and reconciliation against the frozen G4 contract
# ---------------------------------------------------------------------------


def _entry_key(e: Mapping[str, Any]) -> tuple:
    return (e["lane"], e["state_axis"], e["use"])


def derive_manifest_entries(rows: Sequence[Mapping[str, Any]]
                            ) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for lane in sorted({r["denominator_ledger"] for r in rows}):
        lane_rows = [r for r in rows if r["denominator_ledger"] == lane]
        fam = _LANE_FAMILY[lane]
        lens = TRANSMISSION_MAP[fam]
        for axis in CONTINUOUS_AXES:
            col = _STATE_COLUMN[axis]
            eligible = [r for r in lane_rows if r[col] is not None]
            base = {
                "lane": lane, "sampling_family": fam,
                "primary_asset": lens.primary,
                "market_benchmark": lens.market,
                "sector_benchmark": lens.sector,
                "state_axis": axis,
                "eligible_denominator": len(eligible),
                "unique_dates": len({r["event_date"] for r in eligible}),
                "secondary": axis == "credit_hy_oas",
            }
            entries.append({**base, "use": "continuous"})
            if axis in _TAG_AXES:
                entries.append({**base, "use": "categorical"})
    entries.sort(key=_entry_key)
    return entries


def parse_frozen_manifest(g4_text: str) -> list[dict[str, Any]]:
    """The 16 frozen entries parsed from the tracked G4 freeze report."""
    entries = []
    row_re = re.compile(
        r"^\| (frame_complete_historical|designed_contrast) \| (\w+) \| "
        r"(\w+) \| (\w+) \| (\w+) \| `([a-z0-9_]+)`( \(secondary\))? \| "
        r"(continuous|categorical) \| (\d+) \| (\d+) \|")
    for line in g4_text.splitlines():
        m = row_re.match(line)
        if not m:
            continue
        entries.append({
            "lane": m.group(1), "sampling_family": m.group(2),
            "primary_asset": m.group(3), "market_benchmark": m.group(4),
            "sector_benchmark": m.group(5), "state_axis": m.group(6),
            "secondary": bool(m.group(7)), "use": m.group(8),
            "eligible_denominator": int(m.group(9)),
            "unique_dates": int(m.group(10)),
        })
    if len(entries) != 16:
        raise ValueError(f"frozen G4 manifest parse found {len(entries)} "
                         "entries, expected exactly 16")
    entries.sort(key=_entry_key)
    return entries


_RECON_FIELDS = ("lane", "sampling_family", "primary_asset",
                 "market_benchmark", "sector_benchmark", "state_axis",
                 "use", "eligible_denominator", "unique_dates")


def reconcile_manifest(derived: Sequence[Mapping[str, Any]],
                       frozen: Sequence[Mapping[str, Any]]) -> None:
    """Exact 16-entry equality on every reconciliation field; any
    difference - missing entry, extra entry, drifted denominator - raises."""
    if len(derived) != 16 or len(frozen) != 16:
        raise ValueError(f"manifest cardinality drift: derived "
                         f"{len(derived)}, frozen {len(frozen)}, "
                         "expected exactly 16")
    d = {_entry_key(e): e for e in derived}
    f = {_entry_key(e): e for e in frozen}
    if set(d) != set(f):
        raise ValueError(f"manifest key drift: derived-only "
                         f"{sorted(set(d) - set(f))}, frozen-only "
                         f"{sorted(set(f) - set(d))}")
    for key in sorted(d):
        for field in _RECON_FIELDS:
            if d[key][field] != f[key][field]:
                raise ValueError(
                    f"manifest drift at {key}: {field} derived "
                    f"{d[key][field]!r} != frozen {f[key][field]!r}")


# ---------------------------------------------------------------------------
# Outcome readouts via the SHIPPED gate (no parallel engine)
# ---------------------------------------------------------------------------


def _extract(payload: Mapping[str, Any], *, want: Mapping[str, str]
             ) -> dict[str, dict[int, float]]:
    per_h = {int(p["horizon"]): p for p in payload.get("per_horizon", [])}
    if set(per_h) != set(HORIZONS):
        raise ValueError(f"gate horizons {sorted(per_h)} != {HORIZONS}")
    out: dict[str, dict[int, float]] = {}
    for metric, field in want.items():
        vals: dict[int, float] = {}
        for h in HORIZONS:
            v = per_h[h].get(field)
            if v is None:
                raise ValueError(f"gate returned no {field} at {h}d")
            vals[h] = float(v)
        out[metric] = vals
    return out


def compute_readouts(rows: Sequence[Mapping[str, Any]], *,
                     gate: Optional[Callable[..., dict]] = None,
                     db_path: Path | str = G3_PRICE_DB
                     ) -> dict[str, dict[str, Any]]:
    """Per-candidate metric values from the shipped event-study gate.

    Canonical run (market benchmark): absolute asset return, SPY-relative
    AR, SAR. Sector run (sector benchmark): sector-relative AR. Both runs
    must be status-available on the matched ADJUSTED basis; anything else
    fails loudly (expected real split: adjusted 97 / fallback 0 / cross 0).
    """
    use_shipped = gate is None
    if use_shipped:
        gate = esv.build_event_study_validation
        saved = _db.DB_FILE
        _db.DB_FILE = str(db_path)
    try:
        readouts: dict[str, dict[str, Any]] = {}
        for r in rows:
            event = {"event_date": r["event_date"],
                     "market_tickers": [{"symbol": r["primary_asset"]}]}
            canonical = gate(event,
                             benchmark_ticker=r["market_benchmark"])
            sector = gate(event, benchmark_ticker=r["sector_benchmark"])
            for name, payload in (("canonical", canonical),
                                  ("sector", sector)):
                if payload.get("status") != esv.STATUS_AVAILABLE:
                    raise ValueError(
                        f"{r['candidate_id']}: {name} event study not "
                        f"available ({payload.get('status')!r}); the G3 "
                        "eligibility contract expected 97/97")
                basis = _basis_label(payload)
                if basis != "adjusted":
                    raise ValueError(
                        f"{r['candidate_id']}: {name} basis {basis!r} "
                        "drifted from the expected all-adjusted split "
                        "(97 adjusted / 0 fallback / 0 cross)")
            metrics = _extract(canonical, want={
                "absolute_asset_return": "raw_return",
                "spy_relative_ar": "abnormal_return",
                "sar": "sar"})
            metrics.update(_extract(sector, want={
                "sector_relative_ar": "abnormal_return"}))
            readouts[r["candidate_id"]] = {"basis": "adjusted",
                                           "metrics": metrics}
        return readouts
    finally:
        if use_shipped:
            _db.DB_FILE = saved


# ---------------------------------------------------------------------------
# Frozen descriptive summaries
# ---------------------------------------------------------------------------


def _outcome_block(sub_rows: Sequence[Mapping[str, Any]],
                   readouts: Mapping[str, Mapping[str, Any]],
                   *, xs: Optional[Sequence[float]] = None
                   ) -> dict[str, dict[int, dict[str, Any]]]:
    per_metric: dict[str, dict[int, dict[str, Any]]] = {}
    for metric in METRICS:
        per_metric[metric] = {}
        for h in HORIZONS:
            ys = [readouts[r["candidate_id"]]["metrics"][metric][h]
                  for r in sub_rows]
            summary = five_number_summary(ys)
            block: dict[str, Any] = {
                "mean": statistics.fmean(ys),
                "median": summary["median"],
                "p25": summary["p25"], "p75": summary["p75"],
                "min": summary["min"], "max": summary["max"],
                **sign_counts(ys),
            }
            if xs is not None:
                block["spearman_rho"] = spearman_rho(xs, ys)
            per_metric[metric][h] = block
    return per_metric


def summarize_continuous(lane_rows: Sequence[Mapping[str, Any]],
                         state_col: str,
                         readouts: Mapping[str, Mapping[str, Any]]
                         ) -> dict[str, Any]:
    eligible = sorted((r for r in lane_rows if r[state_col] is not None),
                      key=lambda r: r["candidate_id"])
    xs = [float(r[state_col]) for r in eligible]
    return {
        "n": len(eligible),
        "unique_dates": len({r["event_date"] for r in eligible}),
        "state_summary": five_number_summary(xs),
        "per_metric": _outcome_block(eligible, readouts, xs=xs),
    }


def summarize_categorical(lane_rows: Sequence[Mapping[str, Any]],
                          tag_col: str, categories: Sequence[str],
                          readouts: Mapping[str, Mapping[str, Any]]
                          ) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    for cat in categories:
        sub = sorted((r for r in lane_rows if r[tag_col] == cat),
                     key=lambda r: r["candidate_id"])
        uniq = len({r["event_date"] for r in sub})
        cell: dict[str, Any] = {
            "n": len(sub), "unique_dates": uniq,
            "support": ("sufficient_structure"
                        if uniq >= MIN_CELL_UNIQUE_DATES
                        else "insufficient_n"),
        }
        if sub:
            cell["per_metric"] = _outcome_block(sub, readouts)
        cells[cat] = cell
    return {"cells": cells}


def build_readout(rows: Sequence[Mapping[str, Any]],
                  readouts: Mapping[str, Mapping[str, Any]]
                  ) -> dict[str, Any]:
    entries = derive_manifest_entries(rows)
    out = []
    for e in entries:
        lane_rows = [r for r in rows
                     if r["denominator_ledger"] == e["lane"]]
        if e["use"] == "continuous":
            summary = summarize_continuous(
                lane_rows, _STATE_COLUMN[e["state_axis"]], readouts)
        else:
            tag_col, cats = _TAG_AXES[e["state_axis"]]
            summary = summarize_categorical(lane_rows, tag_col, cats,
                                            readouts)
        out.append({**e, "summary": summary})
    return {"readout_version": READOUT_VERSION, "entries": out}


# ---------------------------------------------------------------------------
# Tracked report (deterministic, timestamp-free)
# ---------------------------------------------------------------------------


def _f(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:+.4f}"


_METRIC_LABEL = {
    "absolute_asset_return": "absolute asset return",
    "spy_relative_ar": "SPY-relative AR",
    "sector_relative_ar": "sector-relative AR",
    "sar": "SAR",
}


def _metric_table(per_metric: Mapping[str, Mapping[int, Mapping[str, Any]]],
                  *, with_rho: bool) -> list[str]:
    head = ("| metric | h | mean | median | p25 | p75 | min | max | "
            "pos/zero/neg |" + (" Spearman rho |" if with_rho else ""))
    sep = "|---|---|---|---|---|---|---|---|---|" + (
        "---|" if with_rho else "")
    L = [head, sep]
    for metric in METRICS:
        for h in HORIZONS:
            b = per_metric[metric][h]
            row = (f"| {_METRIC_LABEL[metric]} | {h}d | {_f(b['mean'])} | "
                   f"{_f(b['median'])} | {_f(b['p25'])} | {_f(b['p75'])} | "
                   f"{_f(b['min'])} | {_f(b['max'])} | "
                   f"{b['positive']}/{b['zero']}/{b['negative']} |")
            if with_rho:
                row += f" {_f(b.get('spearman_rho'))} |"
            L.append(row)
    return L


def build_report_text() -> str:
    rows = load_promoted_rows()
    recon = reconcile_universe(rows)
    derived = derive_manifest_entries(rows)
    frozen = parse_frozen_manifest(
        G4_REPORT_PATH.read_text(encoding="utf-8"))
    reconcile_manifest(derived, frozen)
    readouts = compute_readouts(rows)
    basis_counts = {"adjusted": 0, "raw_fallback": 0, "cross": 0}
    for r in readouts.values():
        basis_counts[r["basis"]] += 1
    if basis_counts != {"adjusted": 97, "raw_fallback": 0, "cross": 0}:
        raise ValueError(f"basis split drift: {basis_counts}")
    readout = build_readout(rows, readouts)

    L = [
        "# G6 frozen-manifest readout (Mission G, g0-v1)",
        "",
        f"Readout version: `{READOUT_VERSION}`. First outcome-visible "
        "Mission G surface: the SIXTEEN comparison entries frozen at G4 "
        "(before any outcome was inspected), executed exactly as written "
        "over the 97 promoted historical candidates. Complete raw "
        "evidence surface - every frozen entry, every cell, every metric, "
        "every horizon; nothing curated, nothing hidden, no 'top "
        "findings' section by design.",
        "",
        "## 1. Method contract",
        "",
        "- Universe: the 97 promoted `g_historical_evidence` rows only "
        "(65 frame-complete FOMC + 32 designed-contrast OPEC). The "
        "accepted 86, curated and representative cases, synthetic seeds, "
        "and every other archive row are excluded by construction (the "
        "loader reads only the promoted table).",
        "- Outcome machinery: the shipped event-study gate "
        "(`event_study_validation.build_event_study_validation`) under "
        "the frozen `g3-transmission-map-v1` lenses (FOMC KRE/SPY/XLF; "
        "OPEC XOP/SPY/XLE) and the canonical adjusted-preferred basis. "
        "No parallel implementation.",
        "- Metrics (exactly four): absolute asset return, SPY-relative "
        "AR, sector-relative AR, SAR. The gate also returns CAR; it is "
        "deliberately NOT extracted (no CAR, no SCAR, no VIX-scaled or "
        "ATR metric, no regression beta).",
        f"- Horizons (exactly the shipped triple): "
        f"{', '.join(f'{h}d' for h in HORIZONS)}.",
        "- Continuous association: Spearman rank correlation only - "
        "descriptive, tie-aware, computed between the pre-event state "
        "value and each outcome metric. No p-value, no confidence "
        "interval, no significance label, no Pearson, no regression, no "
        "spline, no binning of continuous axes.",
        "- Categorical cells: the three frozen G4 sign tags only, every "
        "cell reported with N, unique dates, mean, median, p25, p75, "
        "min, max, and sign counts. No pairwise significance test.",
        f"- Structural support floor: MIN_CELL_UNIQUE_DATES = "
        f"{MIN_CELL_UNIQUE_DATES}, reused verbatim from the G4 freeze. "
        "It is a structural support floor only - not statistical power. "
        "Thin cells stay fully visible and are marked `insufficient_n`.",
        "",
        "## 2. Denominator board (all 16 frozen entries)",
        "",
        "| lane | family | axis | use | eligible N | unique dates | "
        "support note |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in readout["entries"]:
        note = "era-bounded secondary subset" if e["secondary"] else "-"
        L.append(f"| {e['lane']} | {e['sampling_family']} | "
                 f"`{e['state_axis']}` | {e['use']} | "
                 f"{e['eligible_denominator']} | {e['unique_dates']} | "
                 f"{note} |")
    L += ["", "## 3. Complete raw evidence surface", ""]
    for e in readout["entries"]:
        head = (f"### {e['lane']} / `{e['state_axis']}` ({e['use']}) - "
                f"{e['primary_asset']} vs {e['market_benchmark']}, "
                f"sector {e['sector_benchmark']}")
        L.append(head)
        L.append("")
        if e["use"] == "continuous":
            s = e["summary"]
            ss = s["state_summary"]
            L.append(f"N = {s['n']}, unique dates = {s['unique_dates']}"
                     + (", era-bounded secondary subset (descriptive "
                        "only)" if e["secondary"] else "") + ".")
            L.append(f"State distribution: min {_f(ss['min'])}, p25 "
                     f"{_f(ss['p25'])}, median {_f(ss['median'])}, p75 "
                     f"{_f(ss['p75'])}, max {_f(ss['max'])}.")
            L.append("")
            L += _metric_table(s["per_metric"], with_rho=True)
        else:
            for cat, cell in e["summary"]["cells"].items():
                L.append(f"**cell `{cat}`** - N = {cell['n']}, unique "
                         f"dates = {cell['unique_dates']}, support = "
                         f"`{cell['support']}`")
                L.append("")
                if cell.get("per_metric"):
                    L += _metric_table(cell["per_metric"], with_rho=False)
                else:
                    L.append("(empty cell - shown, not hidden)")
                L.append("")
        L.append("")
    L += [
        "## 4. Integrity reconciliation",
        "",
        f"- universe: frame {recon['frame_complete_historical']} + "
        f"designed {recon['designed_contrast']} = {recon['total']}; "
        f"unique ids {recon['unique_candidate_ids']}; unique dates "
        f"{recon['unique_event_dates']}",
        "- credit era-bounded subsets: FOMC 20 / OPEC 16 (frozen G4 "
        "denominators, reconciled above)",
        f"- basis split: adjusted {basis_counts['adjusted']} / raw "
        f"fallback {basis_counts['raw_fallback']} / cross "
        f"{basis_counts['cross']} (expected 97/0/0; drift fails the run)",
        "- manifest: derived entries reconciled field-by-field against "
        "the tracked G4 freeze table (16/16; any drift raises)",
        "- accepted-86 contamination: none - the loader reads only "
        "`g_historical_evidence`; no accepted-stage row, curated case, "
        "representative case, or synthetic seed can enter",
        "- mechanism-taxonomy conditioning: none - the promoted table "
        "carries no such column and no G3B/J1 label is read anywhere",
        "- FOMC/OPEC pooling: none - every entry, cell, and statistic "
        "is single-lane by construction",
        "",
        "## 5. Non-claims",
        "",
        "Descriptive conditional association only. No causal regime "
        "effect, no forecast, no trading recommendation, no single-event "
        "significance, no p-value, no confidence interval, no FDR "
        "figure. The designed-contrast lane carries no prevalence claim. "
        "The structural support floor is not an inferential threshold, "
        "and `sufficient_structure` is not a significance statement. "
        "Spearman rho values are descriptive rank associations within "
        "one lane and one axis; they establish no mechanism and no "
        "cross-era equivalence. Not a trading, prediction, or "
        "recommendation surface.",
        "",
        "## 6. Reproduction",
        "",
        "```",
        "python scripts/g6_frozen_manifest_readout.py --emit",
        "python -m unittest tests.test_g6_frozen_manifest_readout",
        "```",
    ]
    return "\n".join(L) + "\n"


def emit_report() -> str:
    text = build_report_text()
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    return f"G6A readout written -> {REPORT_PATH.relative_to(ROOT)}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G6A frozen-manifest execution (read-only).")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.emit:
        print(emit_report())
    if args.json:
        rows = load_promoted_rows()
        reconcile_universe(rows)
        readouts = compute_readouts(rows)
        print(json.dumps(build_readout(rows, readouts), indent=1,
                         sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

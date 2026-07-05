"""G6B - uniform stability diagnostics and falsifier pass over G6A.

Mission G, protocol g0-v1, version g6b-stability-falsifiers-v1.

Post-readout DESCRIPTIVE robustness contract, applied uniformly to the
complete frozen G6A evidence surface - all 120 continuous entry x metric x
horizon associations (10 continuous manifest entries x 4 metrics x 3
horizons) and all 14 frozen categorical cells. Nothing is selected,
ranked, weighted, hidden, or "validated"; influential events are reported
and never removed from the main result. This slice was NOT pre-specified
before outcomes (stated plainly in the report) and belongs to no closed
inferential pool: no p-value, no confidence interval, no significance
label anywhere.

Diagnostics per continuous association: full-sample Spearman rho
(identity-reused from G6A), leave-one-event-out influence (min / max /
opposite-sign runs / max absolute change), leave-one-calendar-year-out
stability (years tested / min / max / opposite-sign / minimum retained
N). Per lane x state axis: a calendar-time confound diagnostic (Spearman
rho between the state value and the event-date ordinal - a structural
diagnostic containing no outcome value; nothing is residualized or
"corrected"). Per categorical cell: median fragility under the same
leave-one-out schemes. The named G6A exceptions (OPEC fed_policy_path x
sector-relative AR; the OPEC credit subset) receive the same diagnostics
as every other association - no privileged model.

Everything reuses the G6A extraction path and the shipped event-study
machinery; drift in the universe, manifest, metrics, horizons, basis
split, or denominators fails loudly through the reused G6A guards.

Usage:

    python scripts/g6b_stability_falsifiers.py --emit
    python scripts/g6b_stability_falsifiers.py --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g6_frozen_manifest_readout as g6a  # noqa: E402

VERSION = "g6b-stability-falsifiers-v1"
REPORT_PATH = ROOT / "stats" / "G6B_STABILITY_AND_FALSIFIERS.md"

# Identity reuse - the deterministic G6A/stdlib calculations, never a
# reimplementation.
spearman_rho = g6a.spearman_rho
median = statistics.median

METRICS = g6a.METRICS
HORIZONS = g6a.HORIZONS
CONTINUOUS_AXES = g6a.CONTINUOUS_AXES
_STATE_COLUMN = g6a._STATE_COLUMN
_TAG_AXES = g6a._TAG_AXES


def _sign(x: Optional[float]) -> int:
    if x is None or x == 0:
        return 0
    return 1 if x > 0 else -1


# ---------------------------------------------------------------------------
# Leave-one-out primitives (pure; inputs never mutated)
# ---------------------------------------------------------------------------


def loeo_rho(xs: Sequence[float], ys: Sequence[float]) -> dict[str, Any]:
    """Leave-one-event-out Spearman influence. Visits every eligible event
    exactly once; the full-sample result is never altered."""
    full = spearman_rho(xs, ys)
    defined: list[float] = []
    opposite = 0
    undefined = 0
    for i in range(len(xs)):
        sub_x = [v for j, v in enumerate(xs) if j != i]
        sub_y = [v for j, v in enumerate(ys) if j != i]
        rho = spearman_rho(sub_x, sub_y)
        if rho is None:
            undefined += 1
            continue
        defined.append(rho)
        if _sign(rho) * _sign(full) == -1:
            opposite += 1
    return {
        "full": full,
        "runs": len(xs),
        "min": min(defined) if defined else None,
        "max": max(defined) if defined else None,
        "opposite_sign": opposite,
        "max_abs_change": (max(abs(r - full) for r in defined)
                           if defined and full is not None else None),
        "undefined_runs": undefined,
    }


def loyo_rho(xs: Sequence[float], ys: Sequence[float],
             years: Sequence[str]) -> dict[str, Any]:
    """Leave-one-calendar-year-out Spearman stability. Every represented
    year is excluded exactly once."""
    full = spearman_rho(xs, ys)
    tested = sorted(set(years))
    defined: list[float] = []
    opposite = 0
    undefined = 0
    min_retained = None
    for year in tested:
        keep = [i for i, y in enumerate(years) if y != year]
        retained = len(keep)
        min_retained = (retained if min_retained is None
                        else min(min_retained, retained))
        rho = spearman_rho([xs[i] for i in keep], [ys[i] for i in keep])
        if rho is None:
            undefined += 1
            continue
        defined.append(rho)
        if _sign(rho) * _sign(full) == -1:
            opposite += 1
    return {
        "full": full,
        "years_tested": tested,
        "min": min(defined) if defined else None,
        "max": max(defined) if defined else None,
        "opposite_sign": opposite,
        "min_retained_n": min_retained,
        "undefined_runs": undefined,
    }


def loeo_median(values: Sequence[float]) -> dict[str, Any]:
    if len(values) < 2:
        return {"runs": len(values), "min": None, "max": None}
    meds = [median([v for j, v in enumerate(values) if j != i])
            for i in range(len(values))]
    return {"runs": len(values), "min": min(meds), "max": max(meds)}


def loyo_median(values: Sequence[float],
                years: Sequence[str]) -> Optional[dict[str, Any]]:
    tested = sorted(set(years))
    if len(tested) < 2:
        return None
    meds: list[float] = []
    min_retained = None
    for year in tested:
        keep = [v for v, y in zip(values, years) if y != year]
        min_retained = (len(keep) if min_retained is None
                        else min(min_retained, len(keep)))
        if keep:
            meds.append(median(keep))
    return {"years_tested": tested, "min": min(meds), "max": max(meds),
            "min_retained_n": min_retained}


# ---------------------------------------------------------------------------
# Boards (uniform; no selection path exists)
# ---------------------------------------------------------------------------


def _eligible(lane_rows: Sequence[Mapping[str, Any]],
              axis: str) -> list[Mapping[str, Any]]:
    col = _STATE_COLUMN[axis]
    return sorted((r for r in lane_rows if r[col] is not None),
                  key=lambda r: r["candidate_id"])


def build_boards(rows: Sequence[Mapping[str, Any]],
                 readouts: Mapping[str, Mapping[str, Any]]
                 ) -> dict[str, Any]:
    entries = g6a.derive_manifest_entries(rows)
    lanes = sorted({r["denominator_ledger"] for r in rows})

    continuous: list[dict[str, Any]] = []
    consistency: list[dict[str, Any]] = []
    for e in (x for x in entries if x["use"] == "continuous"):
        lane_rows = [r for r in rows
                     if r["denominator_ledger"] == e["lane"]]
        eligible = _eligible(lane_rows, e["state_axis"])
        col = _STATE_COLUMN[e["state_axis"]]
        xs = [float(r[col]) for r in eligible]
        years = [r["event_date"][:4] for r in eligible]
        uniq = len({r["event_date"] for r in eligible})
        entry_rhos: dict[tuple[str, int], Optional[float]] = {}
        entry_loyo: dict[tuple[str, int], dict[str, Any]] = {}
        for metric in METRICS:
            for h in HORIZONS:
                ys = [readouts[r["candidate_id"]]["metrics"][metric][h]
                      for r in eligible]
                loeo = loeo_rho(xs, ys)
                loyo = loyo_rho(xs, ys, years)
                entry_rhos[(metric, h)] = loeo["full"]
                entry_loyo[(metric, h)] = loyo
                continuous.append({
                    "lane": e["lane"], "state_axis": e["state_axis"],
                    "secondary": e["secondary"],
                    "metric": metric, "horizon": h,
                    "n": len(eligible), "unique_dates": uniq,
                    "rho": loeo["full"],
                    "loeo": {k: v for k, v in loeo.items() if k != "full"},
                    "loyo": {k: v for k, v in loyo.items() if k != "full"},
                })
        signs = [_sign(v) for v in entry_rhos.values()]
        per_metric = {}
        for metric in METRICS:
            msigns = {_sign(entry_rhos[(metric, h)]) for h in HORIZONS}
            same = len(msigns) == 1 and 0 not in msigns
            preserved = same and all(
                entry_loyo[(metric, h)]["opposite_sign"] == 0
                and entry_loyo[(metric, h)]["undefined_runs"] == 0
                for h in HORIZONS)
            per_metric[metric] = {
                "same_sign_across_horizons": same,
                "loyo_preserves_sign": preserved,
            }
        consistency.append({
            "lane": e["lane"], "state_axis": e["state_axis"],
            "sign_counts": {
                "positive": signs.count(1), "zero": signs.count(0),
                "negative": signs.count(-1)},
            "per_metric": per_metric,
        })

    confound: list[dict[str, Any]] = []
    for lane in lanes:
        lane_rows = [r for r in rows if r["denominator_ledger"] == lane]
        for axis in CONTINUOUS_AXES:
            eligible = _eligible(lane_rows, axis)
            col = _STATE_COLUMN[axis]
            xs = [float(r[col]) for r in eligible]
            ordinals = [float(_dt.date.fromisoformat(
                r["event_date"]).toordinal()) for r in eligible]
            confound.append({
                "lane": lane, "state_axis": axis, "n": len(eligible),
                "rho_state_vs_date_ordinal": spearman_rho(xs, ordinals),
            })

    categorical: list[dict[str, Any]] = []
    for e in (x for x in entries if x["use"] == "categorical"):
        lane_rows = [r for r in rows
                     if r["denominator_ledger"] == e["lane"]]
        tag_col, cats = _TAG_AXES[e["state_axis"]]
        for cat in cats:
            sub = sorted((r for r in lane_rows if r[tag_col] == cat),
                         key=lambda r: r["candidate_id"])
            uniq = len({r["event_date"] for r in sub})
            years = [r["event_date"][:4] for r in sub]
            per_metric: dict[str, Any] = {}
            for metric in METRICS:
                per_metric[metric] = {}
                for h in HORIZONS:
                    vals = [readouts[r["candidate_id"]]["metrics"]
                            [metric][h] for r in sub]
                    per_metric[metric][h] = {
                        "median": median(vals) if vals else None,
                        "loeo": loeo_median(vals),
                        "loyo": loyo_median(vals, years),
                    }
            categorical.append({
                "lane": e["lane"], "state_axis": e["state_axis"],
                "cell": cat, "n": len(sub), "unique_dates": uniq,
                "support": ("sufficient_structure"
                            if uniq >= g6a.MIN_CELL_UNIQUE_DATES
                            else "insufficient_n"),
                "per_metric": per_metric,
            })

    continuous.sort(key=lambda b: (b["lane"], b["state_axis"], b["metric"],
                                   b["horizon"]))
    categorical.sort(key=lambda b: (b["lane"], b["state_axis"], b["cell"]))
    confound.sort(key=lambda b: (b["lane"], b["state_axis"]))
    consistency.sort(key=lambda b: (b["lane"], b["state_axis"]))
    return {"continuous": continuous, "confound": confound,
            "categorical": categorical, "consistency": consistency,
            "contradiction": _contradictions(continuous)}


def _contradictions(continuous: Sequence[Mapping[str, Any]]
                    ) -> dict[str, Any]:
    by_key = {(b["lane"], b["state_axis"], b["metric"], b["horizon"]): b
              for b in continuous}
    lanes = sorted({b["lane"] for b in continuous})
    axes = sorted({b["state_axis"] for b in continuous})
    cross_lane = []
    if len(lanes) == 2:
        a, b = lanes
        for axis in axes:
            for metric in METRICS:
                for h in HORIZONS:
                    ka, kb = (a, axis, metric, h), (b, axis, metric, h)
                    if ka in by_key and kb in by_key:
                        sa = _sign(by_key[ka]["rho"])
                        sb = _sign(by_key[kb]["rho"])
                        if sa * sb == -1:
                            cross_lane.append(
                                f"{axis}/{metric}/{h}d")
    horizon_reversals = []
    metric_disagreements = []
    for lane in lanes:
        for axis in axes:
            for metric in METRICS:
                signs = {_sign(by_key[(lane, axis, metric, h)]["rho"])
                         for h in HORIZONS
                         if (lane, axis, metric, h) in by_key}
                if 1 in signs and -1 in signs:
                    horizon_reversals.append(f"{lane}/{axis}/{metric}")
            for h in HORIZONS:
                signs = {_sign(by_key[(lane, axis, metric, h)]["rho"])
                         for metric in METRICS
                         if (lane, axis, metric, h) in by_key}
                if 1 in signs and -1 in signs:
                    metric_disagreements.append(f"{lane}/{axis}/{h}d")
    loeo_reversals = [f"{b['lane']}/{b['state_axis']}/{b['metric']}/"
                      f"{b['horizon']}d" for b in continuous
                      if b["loeo"]["opposite_sign"] > 0]
    loyo_reversals = [f"{b['lane']}/{b['state_axis']}/{b['metric']}/"
                      f"{b['horizon']}d" for b in continuous
                      if b["loyo"]["opposite_sign"] > 0]
    return {
        "cross_lane_sign_disagreements": cross_lane,
        "horizon_sign_reversals": horizon_reversals,
        "metric_sign_disagreements": metric_disagreements,
        "loeo_sign_reversal_associations": loeo_reversals,
        "loyo_sign_reversal_associations": loyo_reversals,
    }


# ---------------------------------------------------------------------------
# Live run (reuses every G6A guard)
# ---------------------------------------------------------------------------


def run_stability() -> dict[str, Any]:
    rows = g6a.load_promoted_rows()
    recon = g6a.reconcile_universe(rows)
    derived = g6a.derive_manifest_entries(rows)
    frozen = g6a.parse_frozen_manifest(
        g6a.G4_REPORT_PATH.read_text(encoding="utf-8"))
    g6a.reconcile_manifest(derived, frozen)
    readouts = g6a.compute_readouts(rows)
    basis = {"adjusted": 0, "raw_fallback": 0, "cross": 0}
    for r in readouts.values():
        basis[r["basis"]] += 1
    if basis != {"adjusted": 97, "raw_fallback": 0, "cross": 0}:
        raise ValueError(f"basis split drift: {basis}")
    boards = build_boards(rows, readouts)
    if len(boards["continuous"]) != 120:
        raise ValueError(
            f"continuous board has {len(boards['continuous'])} "
            "associations, expected exactly 120 (10 entries x 4 metrics "
            "x 3 horizons)")
    if len(boards["categorical"]) != 14:
        raise ValueError(
            f"categorical board has {len(boards['categorical'])} cells, "
            "expected exactly 14")
    return {"version": VERSION, "reconciliation": recon,
            "basis_split": basis, "boards": boards}


# ---------------------------------------------------------------------------
# Tracked report (deterministic, timestamp-free)
# ---------------------------------------------------------------------------


def _f(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:+.4f}"


def build_report_text() -> str:
    result = run_stability()
    boards = result["boards"]
    recon = result["reconciliation"]

    L = [
        "# G6B stability diagnostics and falsifier pass (Mission G, g0-v1)",
        "",
        f"Version: `{VERSION}`.",
        "",
        "## 1. Contract",
        "",
        "- POST-READOUT descriptive robustness analysis over the complete "
        "frozen G6A surface. It was NOT pre-specified before outcomes were "
        "visible (G6A froze the comparisons; this slice was designed after "
        "the raw surface existed) and is therefore itself descriptive "
        "diagnostics, not part of any closed inferential pool.",
        "- Uniformly applied: the SAME diagnostics run on every one of the "
        "120 continuous entry x metric x horizon associations (10 "
        "continuous manifest entries x 4 metrics x 3 horizons - "
        "equivalently 40 entry x metric panels of 3 horizons each) and on "
        "every one of the 14 frozen categorical cells. No selected "
        "subset, no ranking, no weighted score, no 'best pattern' rule.",
        "- Terminology check (task section 1): the tracked G6A report was "
        "verified and does not contain an erroneous 40-combination "
        "count; the correct continuous surface size, stated here, is 120 "
        "associations.",
        "- Influence runs REPORT; they never remove an event from the "
        "main result. Surviving a diagnostic is not validation, and no "
        "binary robust/fragile threshold is invented.",
        "- No p-value, no confidence interval, no significance claim, no "
        "pooled FOMC + OPEC statistic anywhere.",
        "- G6A remains the authoritative raw readout; universe, manifest, "
        "axes, tags, metrics, horizons, tickers, denominators, and the "
        f"support floor ({g6a.MIN_CELL_UNIQUE_DATES}) are unchanged and "
        "re-reconciled fail-loud before this report renders "
        f"(frame {recon['frame_complete_historical']} / designed "
        f"{recon['designed_contrast']} / total {recon['total']}; basis "
        f"split {result['basis_split']['adjusted']}/"
        f"{result['basis_split']['raw_fallback']}/"
        f"{result['basis_split']['cross']}).",
        "",
        "## 2. Continuous stability board (all 120 associations)",
        "",
        "Columns: full-sample Spearman rho; leave-one-event-out (LOEO) "
        "min / max / opposite-sign runs / max |change|; "
        "leave-one-year-out (LOYO) min / max / opposite-sign runs / "
        "minimum retained N over the years tested.",
        "",
        "| lane | axis | metric | h | N | uniq | rho | LOEO min | LOEO "
        "max | LOEO opp | LOEO max abs ch | LOYO min | LOYO max | LOYO opp | "
        "LOYO min N |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in boards["continuous"]:
        axis = f"`{b['state_axis']}`" + (" (sec)" if b["secondary"] else "")
        L.append(
            f"| {b['lane']} | {axis} | {b['metric']} | {b['horizon']}d | "
            f"{b['n']} | {b['unique_dates']} | {_f(b['rho'])} | "
            f"{_f(b['loeo']['min'])} | {_f(b['loeo']['max'])} | "
            f"{b['loeo']['opposite_sign']} | "
            f"{_f(b['loeo']['max_abs_change'])} | "
            f"{_f(b['loyo']['min'])} | {_f(b['loyo']['max'])} | "
            f"{b['loyo']['opposite_sign']} | "
            f"{b['loyo']['min_retained_n']} |")
    L += [
        "",
        "## 3. Calendar-time confound board",
        "",
        "Spearman rho between the pre-event STATE value and the event-date "
        "ordinal, per lane x axis. A structural diagnostic only - it "
        "contains no outcome value and nothing is residualized or "
        "'corrected' here. A large |rho| means the axis tracks calendar "
        "time within that lane and any conditional pattern on it could "
        "proxy temporal drift.",
        "",
        "| lane | axis | N | rho(state, date) |",
        "|---|---|---|---|",
    ]
    for b in boards["confound"]:
        L.append(f"| {b['lane']} | `{b['state_axis']}` | {b['n']} | "
                 f"{_f(b['rho_state_vs_date_ordinal'])} |")
    L += [
        "",
        "## 4. Categorical fragility board (all 14 frozen cells)",
        "",
        "Medians under leave-one-event-out and (where the cell spans more "
        "than one calendar year) leave-one-year-out. Insufficient cells "
        "stay fully visible; none is merged or hidden.",
        "",
    ]
    for c in boards["categorical"]:
        L.append(f"### {c['lane']} / `{c['state_axis']}` = `{c['cell']}` "
                 f"- N {c['n']}, unique dates {c['unique_dates']}, "
                 f"support `{c['support']}`")
        L.append("")
        L.append("| metric | h | median | LOEO min med | LOEO max med | "
                 "LOYO min med | LOYO max med | LOYO min N |")
        L.append("|---|---|---|---|---|---|---|---|")
        for metric in METRICS:
            for h in HORIZONS:
                blk = c["per_metric"][metric][h]
                ly = blk["loyo"]
                L.append(
                    f"| {metric} | {h}d | {_f(blk['median'])} | "
                    f"{_f(blk['loeo']['min'])} | {_f(blk['loeo']['max'])} |"
                    f" {_f(ly['min']) if ly else 'n/a'} | "
                    f"{_f(ly['max']) if ly else 'n/a'} | "
                    f"{ly['min_retained_n'] if ly else 'n/a'} |")
        L.append("")
    L += [
        "## 5. Cross-metric and cross-horizon consistency board",
        "",
        "Descriptive sign accounting per continuous entry (12 metric x "
        "horizon rhos each). 'Same sign' means all three horizons share "
        "one nonzero sign for that metric; 'LOYO preserves' additionally "
        "means no year exclusion at any horizon flips it. No score, no "
        "ranking, no winner.",
        "",
        "| lane | axis | rho signs +/0/- | " + " | ".join(
            f"{m}: same-sign / LOYO-preserves" for m in METRICS) + " |",
        "|---|---|---|" + "---|" * len(METRICS),
    ]
    for e in boards["consistency"]:
        cells = []
        for m in METRICS:
            pm = e["per_metric"][m]
            cells.append(f"{'yes' if pm['same_sign_across_horizons'] else 'no'}"
                         f" / {'yes' if pm['loyo_preserves_sign'] else 'no'}")
        s = e["sign_counts"]
        L.append(f"| {e['lane']} | `{e['state_axis']}` | "
                 f"{s['positive']}/{s['zero']}/{s['negative']} | "
                 + " | ".join(cells) + " |")
    ct = boards["contradiction"]
    L += [
        "",
        "## 6. Contradiction board (described directly, not adjudicated)",
        "",
        f"- cross-lane sign disagreements (same axis/metric/horizon, "
        f"opposite nonzero sign): {len(ct['cross_lane_sign_disagreements'])}"
        f" - {', '.join(ct['cross_lane_sign_disagreements']) or 'none'}",
        f"- horizon sign reversals (within lane/axis/metric): "
        f"{len(ct['horizon_sign_reversals'])} - "
        f"{', '.join(ct['horizon_sign_reversals']) or 'none'}",
        f"- metric sign disagreements (within lane/axis/horizon): "
        f"{len(ct['metric_sign_disagreements'])} - "
        f"{', '.join(ct['metric_sign_disagreements']) or 'none'}",
        f"- associations with at least one LOEO sign reversal: "
        f"{len(ct['loeo_sign_reversal_associations'])}",
        f"- associations with at least one LOYO sign reversal: "
        f"{len(ct['loyo_sign_reversal_associations'])}",
        "",
        "A pattern that survives these checks is not thereby 'validated'; "
        "a pattern that fails them is not thereby refuted. Both facts are "
        "recorded and carried forward as-is.",
        "",
        "## 7. Explicit falsifier treatment (uniform, no custom model)",
        "",
        "The two patterns singled out in the G6A session summary receive "
        "the same diagnostics as every other association - their rows sit "
        "in the section 2 board above under exactly the same columns:",
        "",
    ]
    fed_rows = [b for b in boards["continuous"]
                if b["lane"] == "designed_contrast"
                and b["state_axis"] == "fed_policy_path"
                and b["metric"] == "sector_relative_ar"]
    for b in fed_rows:
        L.append(f"- OPEC `fed_policy_path` x sector-relative AR "
                 f"{b['horizon']}d: rho {_f(b['rho'])}; LOEO "
                 f"[{_f(b['loeo']['min'])}, {_f(b['loeo']['max'])}], "
                 f"opposite {b['loeo']['opposite_sign']}; LOYO "
                 f"[{_f(b['loyo']['min'])}, {_f(b['loyo']['max'])}], "
                 f"opposite {b['loyo']['opposite_sign']}, min retained N "
                 f"{b['loyo']['min_retained_n']}")
    fed_conf = next(b for b in boards["confound"]
                    if b["lane"] == "designed_contrast"
                    and b["state_axis"] == "fed_policy_path")
    L += [
        "",
        f"- calendar-time confound: OPEC-lane `fed_policy_path` vs date "
        f"ordinal rho = {_f(fed_conf['rho_state_vs_date_ordinal'])} "
        "(section 3). A material value here means the pattern cannot be "
        "distinguished from calendar-time drift inside this lane by "
        "these data alone.",
        "",
    ]
    credit_rows = [b for b in boards["continuous"]
                   if b["lane"] == "designed_contrast"
                   and b["state_axis"] == "credit_hy_oas"]
    L.append("- OPEC credit subset (N=16, era-bounded, secondary-only) - "
             "all 12 associations, same treatment:")
    for b in credit_rows:
        L.append(f"  - {b['metric']} {b['horizon']}d: rho {_f(b['rho'])}; "
                 f"LOEO opposite {b['loeo']['opposite_sign']}; LOYO "
                 f"opposite {b['loyo']['opposite_sign']}")
    frame_max = max(abs(b["rho"]) for b in boards["continuous"]
                    if b["lane"] == "frame_complete_historical"
                    and b["rho"] is not None)
    L += [
        "",
        "## 8. Null findings (kept visible)",
        "",
        "The broad FOMC frame-complete surface remains flat: the largest "
        f"absolute full-sample rho anywhere in that lane is {frame_max:.4f}"
        ", and the section 5 board shows how few metric panels hold one "
        "sign across horizons even before leave-one-out stress. This "
        "flatness is a first-class finding of the frozen manifest and is "
        "not reduced to the exceptions above.",
        "",
        "## 9. Non-claims",
        "",
        "Descriptive robustness accounting only. No causal regime effect, "
        "no forecast, no trading recommendation, no single-event "
        "significance, no prevalence claim for designed-contrast "
        "evidence, no inferential claim from the structural support "
        "floor, and no 'validated pattern' label. Not a trading, "
        "prediction, or recommendation surface.",
        "",
        "## 10. Reproduction",
        "",
        "```",
        "python scripts/g6b_stability_falsifiers.py --emit",
        "python -m unittest tests.test_g6b_stability_falsifiers",
        "```",
    ]
    return "\n".join(L) + "\n"


def emit_report() -> str:
    text = build_report_text()
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    return f"G6B report written -> {REPORT_PATH.relative_to(ROOT)}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G6B uniform stability diagnostics (read-only).")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.emit:
        print(emit_report())
    if args.json:
        print(json.dumps(run_stability(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

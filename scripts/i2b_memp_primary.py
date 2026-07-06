"""I2B - the frozen MEMP primary comparison (Mission I).

The first Mission I slice allowed to compare study-event responses with
ordinary-reference responses. It computes EXACTLY the pre-declared primary
statistic family of the locked i0-v1 protocol (section 13) from the verified
I2A response substrate, and shows the entire closed family. It does not
calibrate, does not run falsifiers, does not rank, and does not interpret which
cell is largest - those belong to I2C.

Frozen estimand (I0 section 13, verbatim semantics):

  For family F, metric m, horizon h:
  - R(F, m, h) = the ordinary-reference multiset { y(t, m, h) } of that cell.
  - Each event's MAGNITUDE PERCENTILE is the mid-rank percentile of |y| within
    { |r| : r in R }:
        pct = (#{|r| < |y|} + 0.5 * #{|r| = |y|}) / |R|.
  - MEMP(F, m, h) = the MEDIAN across the family's events of that magnitude
    percentile.
  - Beside every MEMP, the signed-percentile median: the same mid-rank rule on
    signed values (a location diagnostic, never a replacement for MEMP).

Closed family: exactly 20 cells - FOMC x 4 metrics x {1d, 5d} (8) and
OPEC x 4 metrics x {1d, 5d, 20d} (12). No FOMC 20d cell (structurally
infeasible). Families are never pooled.

Flow: I2A response substrate (built ONCE) -> frozen family partition ->
per-event percentiles -> cell-level MEMP and signed-percentile median. No
candidate universe is rebuilt, no response is recomputed, no second return
methodology exists. Read-only; the substrate's own read-only price access is
the only cache use.

Usage:

    python -m scripts.i2b_memp_primary --emit   # tracked report
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import i2a_response_substrate as i2a  # noqa: E402

CONTRACT_VERSION = "i2b-memp-primary-v1"
REPORT_PATH = ROOT / "stats" / "I2B_MEMP_PRIMARY_COMPARISON.md"

FAMILY_ORDER = ("FOMC", "OPEC")

# Frozen denominators (I0 sections 8, 17; I1 manifests; I2A reconciliation).
EXPECTED_EVENT_N = {"FOMC": 65, "OPEC": 32}
EXPECTED_REFERENCE_N = {
    ("FOMC", 1): 1816, ("FOMC", 5): 1299,
    ("OPEC", 1): 1903, ("OPEC", 5): 1631, ("OPEC", 20): 889,
}
EXPECTED_EVENT_PERCENTILE_ROWS = 904  # 65*2*4 + 32*3*4

CELL_FIELDS = ("family", "horizon", "metric", "event_n", "reference_n",
               "memp", "signed_percentile_median")
EVENT_PCT_FIELDS = ("family", "identity", "anchor_session", "horizon",
                    "metric", "value", "abs_percentile", "signed_percentile")


# ---------------------------------------------------------------------------
# Frozen mid-rank percentile and median aggregation (I0 section 13)
# ---------------------------------------------------------------------------


def mid_rank_percentile(value: float, reference: Sequence[float], *,
                        absolute: bool) -> float:
    """The frozen mid-rank percentile of ``value`` within ``reference``.

    ``pct = (#{r < v} + 0.5 * #{r = v}) / |R|`` where, when ``absolute`` is
    True, ``v = |value|`` and each ``r = |reference_i|`` (the magnitude
    percentile of the primary estimand); when False the signed values are used
    (the location diagnostic). Ties contribute one half each. The reference is
    a MULTISET - duplicates are kept - and must be non-empty.
    """
    n = len(reference)
    if n == 0:
        raise ValueError("empty reference distribution")
    v = abs(value) if absolute else value
    lt = eq = 0
    for r in reference:
        rr = abs(r) if absolute else r
        if rr < v:
            lt += 1
        elif rr == v:
            eq += 1
    return (lt + 0.5 * eq) / n


def memp_of_percentiles(percentiles: Sequence[float]) -> float:
    """MEMP aggregation: the median across events of their percentiles."""
    return statistics.median(percentiles)


# ---------------------------------------------------------------------------
# Frozen family partition and cell computation
# ---------------------------------------------------------------------------


def _assert_frozen_denominators(result: Mapping[str, Any]) -> None:
    cells = result["cells"]
    if len(cells) != 20:
        raise ValueError(f"frozen family is 20 cells; got {len(cells)}")
    for c in cells:
        exp_ev = EXPECTED_EVENT_N[c["family"]]
        if c["event_n"] != exp_ev:
            raise ValueError(
                f"{c['family']} {c['horizon']}d {c['metric']}: event N "
                f"{c['event_n']} != frozen {exp_ev}")
        exp_ref = EXPECTED_REFERENCE_N[(c["family"], c["horizon"])]
        if c["reference_n"] != exp_ref:
            raise ValueError(
                f"{c['family']} {c['horizon']}d {c['metric']}: reference N "
                f"{c['reference_n']} != frozen {exp_ref}")
    n_rows = len(result["event_percentiles"])
    if n_rows != EXPECTED_EVENT_PERCENTILE_ROWS:
        raise ValueError(
            f"event-percentile surface is {EXPECTED_EVENT_PERCENTILE_ROWS} "
            f"rows; got {n_rows}")


def build_primary(substrate: Optional[Mapping[str, Any]] = None, *,
                  expect_frozen: bool = True) -> dict[str, Any]:
    """The complete 20-cell MEMP family plus the 904-row per-event surface.

    ``substrate`` defaults to a single live I2A build (read-only). Pass an
    explicit substrate to drive the frozen partition from an in-memory object
    without rebuilding responses. With ``expect_frozen`` the frozen event /
    reference denominators and the 904-row count are asserted (fail-loud
    before any presentation); tests over synthetic substrates pass it False.
    """
    if substrate is None:
        substrate = i2a.build_substrate()
    records = substrate["records"]

    events: dict[tuple, list] = defaultdict(list)     # key -> [(id, anchor, v)]
    references: dict[tuple, list] = defaultdict(list)  # key -> [value]
    for r in records:
        if r.get("status") != "available":
            continue
        key = (r["family"], r["horizon"], r["metric"])
        if r["membership"] == "event":
            events[key].append(
                (r["identity"], r["anchor_session"], float(r["value"])))
        elif r["membership"] == "reference":
            references[key].append(float(r["value"]))

    cells: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            for metric in i2a.METRICS:
                key = (family, h, metric)
                ref_vals = references.get(key, [])
                ev_items = sorted(events.get(key, []), key=lambda t: t[0])
                abs_pcts: list[float] = []
                signed_pcts: list[float] = []
                for identity, anchor, value in ev_items:
                    ap = mid_rank_percentile(value, ref_vals, absolute=True)
                    sp = mid_rank_percentile(value, ref_vals, absolute=False)
                    abs_pcts.append(ap)
                    signed_pcts.append(sp)
                    rows.append({
                        "family": family, "identity": identity,
                        "anchor_session": anchor, "horizon": h,
                        "metric": metric, "value": value,
                        "abs_percentile": ap, "signed_percentile": sp})
                cells.append({
                    "family": family, "horizon": h, "metric": metric,
                    "event_n": len(ev_items), "reference_n": len(ref_vals),
                    "memp": memp_of_percentiles(abs_pcts) if abs_pcts else None,
                    "signed_percentile_median":
                        memp_of_percentiles(signed_pcts) if signed_pcts
                        else None})

    rows.sort(key=lambda r: (FAMILY_ORDER.index(r["family"]), r["identity"],
                             r["horizon"], i2a.METRICS.index(r["metric"])))
    result = {"contract_version": CONTRACT_VERSION,
              "cells": cells, "event_percentiles": rows}
    if expect_frozen:
        _assert_frozen_denominators(result)
    return result


# ---------------------------------------------------------------------------
# Tracked report - the complete family IS the result (frozen order, no ranking)
# ---------------------------------------------------------------------------


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.6f}"


def render_report(result: Mapping[str, Any]) -> str:
    cells = result["cells"]
    rows = result["event_percentiles"]
    L: list[str] = []
    L.append("# I2B MEMP primary comparison - the complete frozen family "
             "(Mission I)")
    L.append("")
    L.append(f"Contract: `{CONTRACT_VERSION}`, executing the locked i0-v1 "
             "protocol (section 13) over the verified I2A response substrate.")
    L.append("")

    # 1. Frozen-family statement + multiplicity disclosure.
    L.append("## Frozen family")
    L.append("")
    L.append("Exactly **20 primary statistics** (MEMP) were fixed in the "
             "locked protocol before any outcome was compared: FOMC x 4 "
             "metrics x {1d, 5d} (8 cells) and OPEC x 4 metrics x "
             "{1d, 5d, 20d} (12 cells). All 20 are shown below, in frozen "
             "order; no cell was included, reordered, or emphasised because "
             "of its value. FOMC 20d is structurally infeasible (I0 section "
             "8) and has no cell. The two families are never pooled.")
    L.append("")
    L.append("**No p-values are computed and no FDR pool is created.** "
             "Avoiding p-values does not remove multiple-comparison exposure; "
             "the only protection claimed here is that all 20 statistics were "
             "frozen in i0-v1 before any outcome existed and every one is "
             "reported. Calibration (era-matched placement percentiles) and "
             "the falsifiers belong to I2C and are not run here. No cell is "
             "labelled by size and none is described as anything beyond its "
             "printed number.")
    L.append("")

    # 2. Complete primary table (frozen order).
    L.append("## Primary family (all 20 cells, frozen order)")
    L.append("")
    L.append("| family | horizon | metric | event N | reference N | MEMP | "
             "signed-percentile median |")
    L.append("|---|---|---|---|---|---|---|")
    for c in cells:
        L.append(f"| {c['family']} | {c['horizon']}d | {c['metric']} | "
                 f"{c['event_n']} | {c['reference_n']} | {_f(c['memp'])} | "
                 f"{_f(c['signed_percentile_median'])} |")
    L.append("")
    L.append("Reading (mechanics only): a cell's MEMP near 0.5 corresponds to "
             "the family's event absolute responses occupying roughly the "
             "middle of that cell's ordinary reference distribution; the "
             "signed-percentile median reads location under the same mid-rank "
             "rule without absolute values.")
    L.append("")

    # 3. Denominator reconciliation.
    L.append("## Denominator reconciliation")
    L.append("")
    L.append("Every cell's event N equals the frozen study denominator "
             "(FOMC 65, OPEC 32) and every cell's reference N equals the I1 "
             "manifest for that family and horizon; the build fails loudly "
             "before this report if any differ.")
    L.append("")
    L.append("| family | horizon | reference N (frozen) |")
    L.append("|---|---|---|")
    for (family, h), n in EXPECTED_REFERENCE_N.items():
        L.append(f"| {family} | {h}d | {n} |")
    L.append("")
    L.append(f"Full per-event surface: **{len(rows)}** rows "
             "(FOMC 65x2x4 + OPEC 32x3x4), every event-level percentile "
             "preserved, none dropped.")
    L.append("")

    # 4. Method and tie semantics.
    L.append("## Method and tie semantics")
    L.append("")
    L.append("For each cell the ordinary reference multiset R is the complete "
             "set of that cell's reference responses (duplicates kept). An "
             "event's magnitude percentile is the mid-rank percentile of its "
             "absolute response within the absolute references:")
    L.append("")
    L.append("```")
    L.append("pct = ( #{ |r| < |y| } + 0.5 * #{ |r| = |y| } ) / |R|")
    L.append("```")
    L.append("")
    L.append("Ties contribute one half each; an event below every reference "
             "gives 0, above every reference gives 1. MEMP is the median of "
             "those percentiles across the family's events. The "
             "signed-percentile median applies the identical mid-rank rule to "
             "signed values. No statistics-library ranking default is used.")
    L.append("")

    # 5. Full uncurated per-event appendix (frozen order, never by result).
    L.append("## Per-event percentile surface (uncurated, frozen order)")
    L.append("")
    L.append("Order: family, event identity (frozen study-universe order), "
             "horizon, metric. Never ordered by percentile, response "
             "magnitude, or MEMP contribution.")
    L.append("")
    L.append("| family | event | anchor session | horizon | metric | "
             "response | abs mid-rank pct | signed pct |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['family']} | {r['identity']} | "
                 f"{r['anchor_session']} | {r['horizon']}d | {r['metric']} | "
                 f"{_f(r['value'])} | {_f(r['abs_percentile'])} | "
                 f"{_f(r['signed_percentile'])} |")
    L.append("")

    # 6. Next-step boundary.
    L.append("## Next-step boundary")
    L.append("")
    L.append("No calibration, no falsifiers, and no interpretation are "
             "performed in I2B. The complete 20-cell family above IS the "
             "result of this slice. Era-matched placement calibration and the "
             "six frozen falsifiers run in I2C, over this same frozen family "
             "and denominators.")
    L.append("")
    return "\n".join(L) + "\n"


def emit_report() -> None:
    result = build_primary()
    text = render_report(result)
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(
        f"I2B report written -> {REPORT_PATH.relative_to(ROOT)}\n".encode())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="I2B frozen MEMP primary comparison (read-only).")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args(argv)
    if args.emit:
        emit_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

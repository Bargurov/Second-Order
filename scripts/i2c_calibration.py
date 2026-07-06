"""I2C-A - the frozen era-matched placement calibration (Mission I).

Computes the pre-declared 2,000-placement calibration layer of the locked
i0-v1 protocol (section 14) for the complete 20-cell MEMP family, and answers
one question only: where does each observed MEMP sit within the distribution
of the same statistic under the frozen era-matched pseudo-event placement
procedure? It runs none of the six falsifiers, ranks nothing, and uses no
significance vocabulary.

Frozen placement contract (I0 section 14, traced verbatim):

* One PLACEMENT reproduces the family's per-year event-count vector - taken on
  the ANCHOR-SESSION year, the same basis as the pool - drawn WITHOUT
  replacement from that year's eligible ordinary sessions FOR THE GIVEN
  HORIZON (the I1 reference candidates, which already exclude real event
  anchors). Placements are per (family, horizon); the SAME drawn calendar
  feeds all four metrics (no per-metric redraw). B = 2,000; seed = 20180101.
* Each placement's pseudo-MEMP is the identical section-13 pipeline: each drawn
  session is ranked against the FIXED ordinary reference R of the cell. Reading
  A (the one interpretive call, documented): section 13 defines R as
  {y(t) : t eligible} with no anchor-removal step, so a drawn ordinary session
  is ranked self-included; the effect is <= 0.5/|R| per percentile, below the
  section-14 Monte-Carlo resolution, and is applied identically to every
  placement.
* The observed MEMP's calibration position is its mid-rank percentile within
  the 2,000 placement MEMPs, DENOMINATOR 2,000, observed EXTERNAL (never the
  (r+1)/(B+1) p-value guard - p-values are prohibited here). Only the 20
  absolute-magnitude MEMPs are calibrated; the signed-percentile median is
  carried from I2B for display and is NOT calibrated (no 21st statistic).

Flow: I2A substrate (built once) -> I2B observed surface (derived once) ->
frozen placement sampling -> 2,000 placement statistics -> observed percentile.
No price gate is called inside the placement loop; no universe is rebuilt; no
provider/network call. Read-only.

Usage:

    python -m scripts.i2c_calibration --emit   # tracked report
"""
from __future__ import annotations

import argparse
import bisect
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import i2a_response_substrate as i2a  # noqa: E402
from scripts import i2b_memp_primary as i2b  # noqa: E402

CONTRACT_VERSION = "i2c-calibration-v1"
REPORT_PATH = ROOT / "stats" / "I2C_CALIBRATION.md"

SEED = 20180101
B = 2000

FAMILY_ORDER = i2b.FAMILY_ORDER
EXPECTED_REFERENCE_N = i2b.EXPECTED_REFERENCE_N
EXPECTED_EVENT_N = i2b.EXPECTED_EVENT_N

CELL_FIELDS = ("family", "horizon", "metric", "event_n", "reference_n",
               "observed_memp", "signed_percentile_median",
               "calibration_percentile")


# ---------------------------------------------------------------------------
# Frozen percentile primitives (reuse the section-13 mid-rank convention)
# ---------------------------------------------------------------------------


def calibration_percentile(observed: float,
                           placements: Sequence[float]) -> float:
    """Mid-rank percentile of ``observed`` within ``placements`` (denom = B).

    ``(#{p < observed} + 0.5 * #{p = observed}) / len(placements)`` - the same
    frozen mid-rank rule as I2B, with the observed statistic EXTERNAL to the
    placement distribution (no (r+1)/(B+1) continuity guard, which would be a
    prohibited p-value construction).
    """
    return i2b.mid_rank_percentile(observed, placements, absolute=False)


def self_percentiles(values: Sequence[float]) -> list[float]:
    """Magnitude mid-rank percentile of each value within the whole multiset.

    Reading A (section 13, self-included): each value is ranked against the
    fixed absolute reference including itself. Equivalent to
    ``i2b.mid_rank_percentile(v, values, absolute=True)`` for every v, computed
    once with a sorted array so the placement loop is a lookup, never a rescan.
    """
    absv = [abs(v) for v in values]
    ordered = sorted(absv)
    n = len(ordered)
    out = []
    for a in absv:
        lo = bisect.bisect_left(ordered, a)
        hi = bisect.bisect_right(ordered, a)
        out.append((lo + 0.5 * (hi - lo)) / n)
    return out


# ---------------------------------------------------------------------------
# Placement calibration over the single I2A substrate
# ---------------------------------------------------------------------------


def build_calibration(substrate: Optional[Mapping[str, Any]] = None,
                      observed: Optional[Mapping[str, Any]] = None, *,
                      seed: int = SEED, b: int = B,
                      expect_frozen: bool = True) -> dict[str, Any]:
    """The 2,000-placement calibration for the complete 20-cell MEMP family.

    ``substrate`` defaults to a single live I2A build; ``observed`` defaults to
    a single I2B derivation from that substrate. With ``expect_frozen`` the
    frozen denominators, per-year vectors, and B are asserted (fail-loud); a
    synthetic substrate passes it False. Placement selection uses one local
    deterministic RNG seeded at ``seed``, consumed in the fixed order
    family -> horizon -> placement -> year, immune to global RNG state.
    """
    if substrate is None:
        substrate = i2a.build_substrate()
    if observed is None:
        observed = i2b.build_primary(substrate, expect_frozen=expect_frozen)
    observed_by_cell = {(c["family"], c["horizon"], c["metric"]): c
                        for c in observed["cells"]}

    # Partition the substrate (available records only).
    ref_by_cell: dict[tuple, list] = defaultdict(list)      # (f,h,m) -> [(s,v)]
    event_anchor_years: dict[str, Counter] = defaultdict(Counter)
    seen_event: dict[str, set] = defaultdict(set)           # family -> {id}
    for r in substrate["records"]:
        if r.get("status") != "available":
            continue
        if r["membership"] == "reference":
            ref_by_cell[(r["family"], r["horizon"], r["metric"])].append(
                (r["anchor_session"], float(r["value"])))
        elif r["membership"] == "event":
            fam, ident = r["family"], r["identity"]
            if ident not in seen_event[fam]:
                seen_event[fam].add(ident)
                event_anchor_years[fam][r["anchor_session"][:4]] += 1

    # Precompute per-cell self-percentiles (reading A) and per-(f,h) year pools.
    pct_by_session: dict[tuple, dict[str, float]] = {}
    for cell_key, pairs in ref_by_cell.items():
        sessions = [s for s, _ in pairs]
        pcts = self_percentiles([v for _, v in pairs])
        pct_by_session[cell_key] = dict(zip(sessions, pcts))

    pool_by_year: dict[tuple, dict[str, list]] = {}
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            sessions = [s for s, _ in ref_by_cell[(family, h, i2a.METRICS[0])]]
            by_year: dict[str, list] = defaultdict(list)
            for s in sessions:
                by_year[s[:4]].append(s)
            pool_by_year[(family, h)] = {y: sorted(v)
                                        for y, v in by_year.items()}

    rng = np.random.default_rng(seed)  # ONE local stream, fixed consumption

    placements: dict[tuple, dict[str, Any]] = {}
    for family in FAMILY_ORDER:
        per_year = dict(sorted(event_anchor_years[family].items()))
        years = list(per_year)  # sorted years with real events
        for h in i2a.FEASIBLE_HORIZONS[family]:
            pools = pool_by_year[(family, h)]
            for y in years:
                have = len(pools.get(y, []))
                if have < per_year[y]:
                    raise ValueError(
                        f"{family} {h}d {y}: eligible pool {have} < required "
                        f"placement count {per_year[y]} - cannot place "
                        "without replacement")
            year_arrays = {y: np.array(pools[y]) for y in years}
            sessions_list: list[tuple] = []
            memp: dict[str, list] = {m: [] for m in i2a.METRICS}
            for _ in range(b):
                drawn: list[str] = []
                for y in years:
                    pick = rng.choice(year_arrays[y], size=per_year[y],
                                      replace=False)
                    drawn.extend(pick.tolist())
                sessions_list.append(tuple(drawn))
                for m in i2a.METRICS:
                    lut = pct_by_session[(family, h, m)]
                    memp[m].append(statistics.median(lut[s] for s in drawn))
            placements[(family, h)] = {
                "per_year_event_counts": per_year,
                "per_year_pool_sizes": {y: len(pools[y]) for y in years},
                "sessions": sessions_list, "memp": memp}

    cells: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            for m in i2a.METRICS:
                obs = observed_by_cell[(family, h, m)]
                dist = placements[(family, h)]["memp"][m]
                cells.append({
                    "family": family, "horizon": h, "metric": m,
                    "event_n": obs["event_n"],
                    "reference_n": obs["reference_n"],
                    "observed_memp": obs["memp"],
                    "signed_percentile_median": obs["signed_percentile_median"],
                    "calibration_percentile":
                        calibration_percentile(obs["memp"], dist)})

    result = {"contract_version": CONTRACT_VERSION, "seed": seed, "B": b,
              "cells": cells, "placements": placements}
    if expect_frozen:
        _assert_frozen(result)
    return result


def _assert_frozen(result: Mapping[str, Any]) -> None:
    if result["B"] != B or result["seed"] != SEED:
        raise ValueError(f"frozen seed/B changed: {result['seed']}/{result['B']}")
    if len(result["cells"]) != 20:
        raise ValueError(f"frozen family is 20 cells; got {len(result['cells'])}")
    for c in result["cells"]:
        if c["event_n"] != EXPECTED_EVENT_N[c["family"]]:
            raise ValueError(f"{c['family']} event N {c['event_n']} changed")
        if c["reference_n"] != EXPECTED_REFERENCE_N[(c["family"], c["horizon"])]:
            raise ValueError(
                f"{c['family']} {c['horizon']}d reference N changed")
    for (family, h), pl in result["placements"].items():
        if len(pl["sessions"]) != result["B"]:
            raise ValueError(
                f"{family} {h}d completed {len(pl['sessions'])} != {result['B']}")
        if sum(pl["per_year_event_counts"].values()) != EXPECTED_EVENT_N[family]:
            raise ValueError(f"{family} {h}d per-year vector != event N")


# ---------------------------------------------------------------------------
# Tracked report (frozen order; the complete calibrated family IS the result)
# ---------------------------------------------------------------------------


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.6f}"


def render_report(result: Mapping[str, Any]) -> str:
    cells = result["cells"]
    placements = result["placements"]
    L: list[str] = []
    L.append("# I2C-A era-matched placement calibration (Mission I)")
    L.append("")
    L.append(f"Contract: `{CONTRACT_VERSION}`, executing the locked i0-v1 "
             "calibration layer (section 14) over the verified I2A substrate "
             "and the frozen I2B 20-cell MEMP family.")
    L.append("")

    L.append("## Frozen calibration statement")
    L.append("")
    L.append(f"Exactly **20** MEMP statistics were frozen before any outcome "
             "was compared; all 20 are calibrated below, in frozen I2B order. "
             f"**B = 2,000** era-matched pseudo-event placements per (family, "
             f"horizon); fixed seed **20180101**. The output is a "
             "percentile-of-placements only: **no p-values**, no significance "
             "threshold, no confidence interval, and no new FDR pool (the "
             "accepted-86 and Mission G pools stay separate). Families are "
             "never pooled; FOMC 20d is structurally infeasible and has no "
             "cell. No cell is labelled by size or ranked.")
    L.append("")

    L.append("## Calibrated family (all 20 cells, frozen order)")
    L.append("")
    L.append("| family | horizon | metric | event N | reference N | "
             "observed MEMP | calibration percentile |")
    L.append("|---|---|---|---|---|---|---|")
    for c in cells:
        L.append(f"| {c['family']} | {c['horizon']}d | {c['metric']} | "
                 f"{c['event_n']} | {c['reference_n']} | "
                 f"{_f(c['observed_memp'])} | "
                 f"{_f(c['calibration_percentile'])} |")
    L.append("")
    L.append("Reading (mechanics only): the calibration percentile is the "
             "position of the observed MEMP within its 2,000 era-matched "
             "placement MEMPs under the section-13 mid-rank rule; 0.5 means "
             "the observed value sits at the middle of the placement "
             "distribution. The I2B signed-percentile median is a descriptive "
             "diagnostic and is not calibrated (calibrating it would create a "
             "statistic outside the frozen family of 20).")
    L.append("")

    L.append("## Placement reconciliation")
    L.append("")
    L.append("| family | horizon | expected placements | completed | "
             "per-year event counts (anchor-session year) |")
    L.append("|---|---|---|---|---|")
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            pl = placements[(family, h)]
            per_year = ", ".join(f"{y}:{n}"
                                 for y, n in pl["per_year_event_counts"].items())
            L.append(f"| {family} | {h}d | {result['B']} | "
                     f"{len(pl['sessions'])} | {per_year} |")
    L.append("")
    L.append("Every placement reproduces the family's per-year event-count "
             "vector exactly, drawn without replacement from that year's "
             "eligible ordinary sessions for the horizon; every year's pool "
             "supplies its required count (no failure, no replacement). The "
             "eligible pool is the I1 reference set, which already excludes "
             "real event anchors, so no real study event is ever placed.")
    L.append("")

    L.append("## Method")
    L.append("")
    L.append("One placement reproduces the family's per-year event count on "
             "the anchor-session year and draws, per year, that many distinct "
             "sessions uniformly without replacement from the horizon's "
             "eligible ordinary pool. The same drawn calendar feeds all four "
             "metrics. Each placement's pseudo-MEMP is the identical "
             "section-13 pipeline: each drawn session's absolute response is "
             "given its mid-rank percentile within the cell's fixed ordinary "
             "reference (self-included, per section 13's fixed-R definition), "
             "and the placement MEMP is the median across the drawn sessions. "
             "The observed MEMP's calibration percentile is its mid-rank "
             "position within the 2,000 placement MEMPs, denominator 2,000, "
             "observed external. Selection uses one local deterministic RNG "
             "seeded at 20180101, consumed in the fixed order family, horizon, "
             "placement, year.")
    L.append("")

    L.append("## Boundary")
    L.append("")
    L.append("This slice computes the calibration position only. Not yet run "
             "(they belong to I2C-B): F1 LOYO (leave-one-year-out), F2 LOEO "
             "(leave-one-event-out), F3 overlap decimation, F4 cross-metric "
             "consistency, F5 cross-horizon consistency, and the F6 central-50 "
             "percent calibration-position interpretation. No interpretation "
             "of any cell is made here.")
    L.append("")
    return "\n".join(L) + "\n"


def emit_report() -> None:
    result = build_calibration()
    text = render_report(result)
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(
        f"I2C report written -> {REPORT_PATH.relative_to(ROOT)}\n".encode())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="I2C-A era-matched placement calibration (read-only).")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args(argv)
    if args.emit:
        emit_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

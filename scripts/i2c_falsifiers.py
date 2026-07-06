"""I2C-B - the frozen falsifier battery F1-F6 (Mission I).

Runs exactly the six falsifiers frozen in I0 section 15 against the complete
20-cell Mission I result surface. It answers only which observed MEMP
directions survive ordinary perturbations, which depend on specific years or
events, which change under canonical overlap decimation, and where
metrics/horizons disagree. No new robustness test, no ranking, no combined
score, no significance vocabulary, no Mission-I narrative.

Direction is the I0 sign convention around ``MEMP - 0.5``, using the frozen
G6B rule: ``sign(0) = 0`` and a flip is counted only when
``sign(perturbed) * sign(full) == -1`` (an exact 0.5 is never a flip).

Falsifier semantics traced from I0 section 15:

* **F1 LOYO** - excluding each calendar year's *events and ordinary dates*, so
  the reference R shrinks; MEMP is recomputed against the reduced R (this
  follows I0 section 15's "and ordinary dates" over the looser task-summary
  phrasing, which read R-fixed). Year membership is the session-date year.
* **F2 LOEO** - removing one *event* at a time; R stays fixed, so the leave-one
  MEMP is the median of the surviving I2B event percentiles.
* **F3 overlap decimation** - recomputing each MEMP against the canonical
  greedy earliest-first disjoint-window reference subset (I0 section 9 / I1A:
  starts >= h+1 apart), the SAME reference sessions across all four metrics.
* **F4** - per family x horizon, the sign counts across the four metrics.
* **F5** - per family x metric, whether the feasible horizons agree on sign.
* **F6** - whether the I2C-A calibration percentile lands inside the central
  50 percent, [0.25, 0.75] inclusive (a position diagnostic, not a test).

Flow: one I2A substrate -> one I2B observed surface -> one I2C-A calibration ->
F1-F6 in memory. The observed MEMPs and calibration percentiles are carried
through unchanged; no price gate is called in any falsifier loop, no universe
or substrate is rebuilt, no provider/network/DB call. Read-only.

Usage:

    python -m scripts.i2c_falsifiers --emit   # tracked report
"""
from __future__ import annotations

import argparse
import bisect
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts import i2a_response_substrate as i2a  # noqa: E402
from scripts import i2b_memp_primary as i2b  # noqa: E402
from scripts import i2c_calibration as i2c  # noqa: E402

CONTRACT_VERSION = "i2c-falsifiers-v1"
REPORT_PATH = ROOT / "stats" / "I2C_FALSIFIERS.md"

FAMILY_ORDER = i2b.FAMILY_ORDER
EXPECTED_EVENT_N = i2b.EXPECTED_EVENT_N
EXPECTED_F3_REFERENCE_N = {("FOMC", 1): 927, ("FOMC", 5): 233,
                          ("OPEC", 1): 960, ("OPEC", 5): 287, ("OPEC", 20): 51}

CELL_FIELDS = ("family", "horizon", "metric", "observed_memp",
               "calibration_percentile", "loyo_runs", "loyo_flips",
               "loyo_flip_years", "loeo_runs", "loeo_flips",
               "loeo_flip_identities", "original_reference_n",
               "f3_reference_n", "f3_decimated_memp", "f3_change", "f3_flip",
               "f6_position")


# ---------------------------------------------------------------------------
# Direction / flip convention (frozen, as in G6B) and percentile helper
# ---------------------------------------------------------------------------


def _sign(x: float) -> int:
    if x == 0:
        return 0
    return 1 if x > 0 else -1


def sign_dir(memp: float) -> int:
    """The frozen direction of a cell: ``sign(MEMP - 0.5)`` (0 at exactly 0.5)."""
    return _sign(memp - 0.5)


def flipped(perturbed_memp: float, full_memp: float) -> bool:
    """A sign flip under the G6B convention: strict opposite directions only.

    ``True`` iff ``sign(perturbed - 0.5) * sign(full - 0.5) == -1`` - an exact
    0.5 on either side yields sign 0 and is never counted as a flip.
    """
    return sign_dir(perturbed_memp) * sign_dir(full_memp) == -1


def _abs_mid_rank(value: float, sorted_abs_ref: Sequence[float]) -> float:
    """Section-13 magnitude mid-rank of ``value`` within a pre-sorted ``|R|``.

    Equivalent to ``i2b.mid_rank_percentile(value, R, absolute=True)`` but O(log
    N) against a reference sorted once, so no falsifier loop rescans R.
    """
    a = abs(value)
    n = len(sorted_abs_ref)
    lo = bisect.bisect_left(sorted_abs_ref, a)
    hi = bisect.bisect_right(sorted_abs_ref, a)
    return (lo + 0.5 * (hi - lo)) / n


# ---------------------------------------------------------------------------
# Pure falsifier primitives
# ---------------------------------------------------------------------------


def loeo_surface(abs_pcts: Mapping[str, float],
                 full_memp: float) -> list[dict[str, Any]]:
    """F2: leave-one-event-out with R fixed. Every event visited exactly once;
    the leave-one MEMP is the median of the surviving event percentiles."""
    ids = list(abs_pcts)
    out = []
    for e_id in ids:
        others = [abs_pcts[j] for j in ids if j != e_id]
        memp = statistics.median(others)
        out.append({"identity": e_id, "memp": memp,
                    "flip": flipped(memp, full_memp)})
    return out


def loyo_surface(events: Sequence[tuple], references: Sequence[tuple],
                 full_memp: float) -> list[dict[str, Any]]:
    """F1: leave-one-year-out removing the year's events AND ordinary dates.

    ``events`` are ``(identity, anchor_session, value, year)``; ``references``
    are ``(session, value, year)``. For each year with events, both sides drop
    that year and the surviving events are re-ranked against the reduced R.
    """
    years = sorted({yr for *_, yr in events})
    out = []
    for y in years:
        reduced = sorted(abs(v) for _, v, yr in references if yr != y)
        survivors = [val for _, _, val, yr in events if yr != y]
        pcts = [_abs_mid_rank(v, reduced) for v in survivors]
        memp = statistics.median(pcts)
        out.append({"year": y, "memp": memp,
                    "flip": flipped(memp, full_memp)})
    return out


def decimated_memp(event_values: Sequence[float],
                   subset_ref_values: Sequence[float]) -> float:
    """F3: MEMP of the unchanged events against the decimated reference set."""
    reduced = sorted(abs(v) for v in subset_ref_values)
    return statistics.median(_abs_mid_rank(v, reduced) for v in event_values)


def f4_summary(metric_memps: Mapping[str, float]) -> dict[str, Any]:
    """F4: per family x horizon, sign counts over the four metric directions."""
    signs = {m: sign_dir(v) for m, v in metric_memps.items()}
    vals = list(signs.values())
    return {"signs": signs,
            "sign_counts": {"positive": vals.count(1),
                            "zero": vals.count(0),
                            "negative": vals.count(-1)}}


def f5_summary(horizon_memps: Mapping[int, float]) -> dict[str, Any]:
    """F5: per family x metric, whether feasible horizons share one sign."""
    signs = {h: sign_dir(v) for h, v in horizon_memps.items()}
    distinct = set(signs.values())
    return {"signs": signs,
            "same_across_horizons": len(distinct) == 1 and 0 not in distinct}


def f6_position(calibration_percentile: float) -> str:
    """F6: inside/outside the central 50 percent, [0.25, 0.75] inclusive."""
    return "inside" if 0.25 <= calibration_percentile <= 0.75 else "outside"


# ---------------------------------------------------------------------------
# Battery over the single substrate / observed / calibration
# ---------------------------------------------------------------------------


def build_falsifiers(substrate: Optional[Mapping[str, Any]] = None,
                     observed: Optional[Mapping[str, Any]] = None,
                     calibration: Optional[Mapping[str, Any]] = None,
                     lanes: Optional[Mapping[str, Any]] = None, *,
                     expect_frozen: bool = True) -> dict[str, Any]:
    """The complete F1-F6 battery for the frozen 20-cell family, in memory."""
    if substrate is None:
        substrate = i2a.build_substrate()
    if observed is None:
        observed = i2b.build_primary(substrate, expect_frozen=expect_frozen)
    if calibration is None:
        calibration = i2c.build_calibration(substrate, observed,
                                            expect_frozen=expect_frozen)
    if lanes is None:
        lanes = i1.build_universe()

    events: dict[tuple, list] = defaultdict(list)
    references: dict[tuple, list] = defaultdict(list)
    for r in substrate["records"]:
        if r.get("status") != "available":
            continue
        key = (r["family"], r["horizon"], r["metric"])
        if r["membership"] == "event":
            events[key].append((r["identity"], r["anchor_session"],
                                float(r["value"]), r["anchor_session"][:4]))
        elif r["membership"] == "reference":
            references[key].append((r["anchor_session"], float(r["value"]),
                                    r["anchor_session"][:4]))

    abs_pcts: dict[tuple, dict[str, float]] = defaultdict(dict)
    for row in observed["event_percentiles"]:
        abs_pcts[(row["family"], row["horizon"], row["metric"])][
            row["identity"]] = row["abs_percentile"]

    observed_memp = {(c["family"], c["horizon"], c["metric"]): c["memp"]
                     for c in observed["cells"]}
    observed_ref_n = {(c["family"], c["horizon"], c["metric"]):
                      c["reference_n"] for c in observed["cells"]}
    cal_pct = {(c["family"], c["horizon"], c["metric"]):
               c["calibration_percentile"] for c in calibration["cells"]}

    # F3 canonical subset once per (family, horizon), shared across metrics.
    f3_subset: dict[tuple, set] = {}
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            idx = i1.canonical_non_overlapping_windows(
                lanes[family].cells[h].candidate_indices, h)
            dates = {lanes[family].joint_sessions[i] for i in idx}
            f3_subset[(family, h)] = dates

    cells: list[dict[str, Any]] = []
    loyo_all: dict[tuple, list] = {}
    loeo_all: dict[tuple, list] = {}
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            subset_dates = f3_subset[(family, h)]
            for m in i2a.METRICS:
                key = (family, h, m)
                full = observed_memp[key]

                loyo = loyo_surface(events[key], references[key], full)
                loeo = loeo_surface(abs_pcts[key], full)
                loyo_all[key] = loyo
                loeo_all[key] = loeo

                subset_vals = [v for s, v, _ in references[key]
                               if s in subset_dates]
                dec_memp = decimated_memp([val for _, _, val, _ in events[key]],
                                          subset_vals)

                cells.append({
                    "family": family, "horizon": h, "metric": m,
                    "observed_memp": full, "calibration_percentile": cal_pct[key],
                    "loyo_runs": len(loyo),
                    "loyo_flips": sum(1 for x in loyo if x["flip"]),
                    "loyo_flip_years": [x["year"] for x in loyo if x["flip"]],
                    "loeo_runs": len(loeo),
                    "loeo_flips": sum(1 for x in loeo if x["flip"]),
                    "loeo_flip_identities":
                        [x["identity"] for x in loeo if x["flip"]],
                    "original_reference_n": observed_ref_n[key],
                    "f3_reference_n": len(subset_vals),
                    "f3_decimated_memp": dec_memp,
                    "f3_change": dec_memp - full,
                    "f3_flip": flipped(dec_memp, full),
                    "f6_position": f6_position(cal_pct[key])})

    f4 = []
    for family in FAMILY_ORDER:
        for h in i2a.FEASIBLE_HORIZONS[family]:
            summary = f4_summary({m: observed_memp[(family, h, m)]
                                  for m in i2a.METRICS})
            f4.append({"family": family, "horizon": h, **summary})

    f5 = []
    for family in FAMILY_ORDER:
        for m in i2a.METRICS:
            summary = f5_summary({h: observed_memp[(family, h, m)]
                                  for h in i2a.FEASIBLE_HORIZONS[family]})
            f5.append({"family": family, "metric": m, **summary})

    result = {"contract_version": CONTRACT_VERSION, "cells": cells,
              "loyo": loyo_all, "loeo": loeo_all, "f4": f4, "f5": f5}
    if expect_frozen:
        _assert_frozen(result, observed_memp)
    return result


def _assert_frozen(result: Mapping[str, Any],
                   observed_memp: Mapping[tuple, float]) -> None:
    if len(result["cells"]) != 20:
        raise ValueError(f"frozen family is 20 cells; got {len(result['cells'])}")
    for c in result["cells"]:
        key = (c["family"], c["horizon"], c["metric"])
        if c["observed_memp"] != observed_memp[key]:
            raise ValueError(f"{key} observed MEMP drifted")
        if c["loyo_runs"] != 8:
            raise ValueError(f"{key} LOYO runs {c['loyo_runs']} != 8")
        if c["loeo_runs"] != EXPECTED_EVENT_N[c["family"]]:
            raise ValueError(f"{key} LOEO runs {c['loeo_runs']} != event N")
        if c["f3_reference_n"] != EXPECTED_F3_REFERENCE_N[(c["family"], c["horizon"])]:
            raise ValueError(
                f"{key} F3 reference N {c['f3_reference_n']} != canonical count")
        if c["calibration_percentile"] in (0.25, 0.75):
            raise ValueError(f"{key} sits on an F6 boundary; inclusivity matters")


# ---------------------------------------------------------------------------
# Tracked report (frozen order; complete surface, no best-of summary)
# ---------------------------------------------------------------------------


def _f(x: float) -> str:
    return f"{x:.6f}"


def _label(c: Mapping[str, Any]) -> str:
    return f"{c['family']} | {c['horizon']}d | {c['metric']}"


def render_report(result: Mapping[str, Any]) -> str:
    cells = result["cells"]
    L: list[str] = []
    L.append("# I2C-B frozen falsifier battery (Mission I)")
    L.append("")
    L.append(f"Contract: `{CONTRACT_VERSION}`, running exactly the six I0 "
             "section-15 falsifiers against the frozen I2B 20-cell MEMP family "
             "and the I2C-A calibration. Direction is `sign(MEMP - 0.5)` under "
             "the frozen G6B convention (`sign(0) = 0`; a flip requires strict "
             "opposite signs). This slice reports mechanical stability facts "
             "only - no ranking, no combined score, no significance language, "
             "and no overall Mission-I interpretation.")
    L.append("")

    # A. complete 20-cell table
    L.append("## A. Complete 20-cell falsifier surface (frozen order)")
    L.append("")
    L.append("| family | horizon | metric | observed MEMP | calibration pct | "
             "LOYO runs | LOYO flips | LOEO runs | LOEO flips | orig. ref N | "
             "F3 dec. N | F3 dec. MEMP | F3 change | F3 flip | F6 central-50% |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        L.append(
            f"| {c['family']} | {c['horizon']}d | {c['metric']} | "
            f"{_f(c['observed_memp'])} | {_f(c['calibration_percentile'])} | "
            f"{c['loyo_runs']} | {c['loyo_flips']} | {c['loeo_runs']} | "
            f"{c['loeo_flips']} | {c['original_reference_n']} | "
            f"{c['f3_reference_n']} | {_f(c['f3_decimated_memp'])} | "
            f"{c['f3_change']:+.6f} | {'yes' if c['f3_flip'] else 'no'} | "
            f"{c['f6_position']} |")
    L.append("")
    L.append("`sign(MEMP - 0.5)` gives each cell's frozen direction; a flip is "
             "a strict sign reversal of that quantity. F6 states whether the "
             "calibration percentile falls inside `[0.25, 0.75]`; it is a "
             "position label, not a test outcome.")
    L.append("")

    # B. full LOYO appendix
    L.append("## B. Full leave-one-year-out (F1) appendix")
    L.append("")
    L.append("**F1 reference convention.** F1 follows I0 section 15, which "
             "removes each calendar year's *events and ordinary dates* - so "
             "the reference R shrinks and every surviving event is re-ranked "
             "against the reduced R. This differs from an R-fixed reading "
             "(keep each event's original percentile and take the median of "
             "survivors); the two can produce different flip counts for cells "
             "near 0.5. The authoritative I0 reading (R reduced) is used "
             "throughout, and is the basis of the LOYO flip counts in Section "
             "A.")
    L.append("")
    L.append("Each year removes that calendar year's events and ordinary "
             "reference dates; the surviving events are re-ranked against the "
             "reduced reference. Every year is shown.")
    L.append("")
    for c in cells:
        L.append(f"### {_label(c)}")
        L.append("")
        L.append("| removed year | leave-year-out MEMP | sign flip |")
        L.append("|---|---|---|")
        for row in result["loyo"][(c["family"], c["horizon"], c["metric"])]:
            L.append(f"| {row['year']} | {_f(row['memp'])} | "
                     f"{'yes' if row['flip'] else 'no'} |")
        L.append("")

    # C. full LOEO appendix
    L.append("## C. Full leave-one-event-out (F2) appendix")
    L.append("")
    L.append("Each event is removed once with the reference held fixed; the "
             "leave-one MEMP is the median of the surviving event percentiles. "
             "Every event is shown.")
    L.append("")
    for c in cells:
        L.append(f"### {_label(c)}")
        L.append("")
        L.append("| removed event | leave-event-out MEMP | sign flip |")
        L.append("|---|---|---|")
        for row in result["loeo"][(c["family"], c["horizon"], c["metric"])]:
            L.append(f"| {row['identity']} | {_f(row['memp'])} | "
                     f"{'yes' if row['flip'] else 'no'} |")
        L.append("")

    # D. F4 cross-metric
    L.append("## D. F4 cross-metric consistency (per family x horizon)")
    L.append("")
    L.append("| family | horizon | raw_return | spy_relative_ar | "
             "sector_relative_ar | sar | positive | zero | negative |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in result["f4"]:
        s = r["signs"]
        cnt = r["sign_counts"]
        L.append(f"| {r['family']} | {r['horizon']}d | {s['raw_return']:+d} | "
                 f"{s['spy_relative_ar']:+d} | {s['sector_relative_ar']:+d} | "
                 f"{s['sar']:+d} | {cnt['positive']} | {cnt['zero']} | "
                 f"{cnt['negative']} |")
    L.append("")
    L.append("Signs are `sign(MEMP - 0.5)` per metric (`+1` above 0.5, `-1` "
             "below, `0` exactly at 0.5). The counts describe agreement among "
             "the four metrics; they are not a mechanism claim.")
    L.append("")

    # E. F5 cross-horizon
    L.append("## E. F5 cross-horizon consistency (per family x metric)")
    L.append("")
    L.append("| family | metric | 1d | 5d | 20d | horizons agree on sign |")
    L.append("|---|---|---|---|---|---|")
    for r in result["f5"]:
        s = r["signs"]
        cell = {h: f"{s[h]:+d}" for h in s}
        L.append(f"| {r['family']} | {r['metric']} | {cell.get(1, 'n/a')} | "
                 f"{cell.get(5, 'n/a')} | {cell.get(20, 'n/a')} | "
                 f"{'yes' if r['same_across_horizons'] else 'no'} |")
    L.append("")
    L.append("`n/a` marks an infeasible horizon (FOMC has no 20d primary "
             "cell). Agreement requires one shared non-zero sign across every "
             "feasible horizon.")
    L.append("")

    # Boundary
    L.append("## Boundary")
    L.append("")
    L.append("The six falsifiers stand separately; they are not averaged, "
             "scored, graded, or combined into any index. This slice states "
             "mechanical stability facts only. The overall Mission-I "
             "interpretation is deferred to the closeout task.")
    L.append("")
    return "\n".join(L) + "\n"


def emit_report() -> None:
    result = build_falsifiers()
    text = render_report(result)
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(
        f"I2C falsifier report written -> {REPORT_PATH.relative_to(ROOT)}\n"
        .encode())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="I2C-B frozen falsifier battery F1-F6 (read-only).")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args(argv)
    if args.emit:
        emit_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

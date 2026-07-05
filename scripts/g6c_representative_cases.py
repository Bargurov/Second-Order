"""G6C - state-anchored representative cases and finance interpretation.

Mission G, protocol g0-v1, version g6c-representative-cases-v1.

Selects a bounded representative-case library from the completed G6A raw
surface and G6B stability diagnostics WITHOUT letting outcome values into
selection. Three frozen roles, each anchored at the Q25 and Q75 of its
state axis (six slots): Role A - the stable-but-confounded OPEC
fed_policy_path association; Role B - the fragile, era-bounded OPEC
credit subset; Role C - the broad FOMC null. Selection is post-readout
and disclosed as such; anchors reuse the G6A inclusive quantile
convention; the selector minimizes |state - target| with ties broken by
event date then candidate id. There is no override path, no
largest-return path, and no famous-event path; a candidate selected by
two roles keeps both assignments and is rendered once.

Interpretation ceiling carried forward from G6B (hard floor): the broad
surface is predominantly flat/fragile/contradictory; the OPEC fed-path
pattern is a stable descriptive association with unresolved calendar-time
confounding (never validated/causal/predictive); credit stays era-bounded
secondary; the FOMC flat surface is a substantive null result.
Representative cases are illustrations, never proof.

Usage:

    python scripts/g6c_representative_cases.py --select   # slots as JSON
    python scripts/g6c_representative_cases.py --emit     # tracked report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g6_frozen_manifest_readout as g6a  # noqa: E402
from scripts import g6b_stability_falsifiers as g6b  # noqa: E402

VERSION = "g6c-representative-cases-v1"
REPORT_PATH = ROOT / "stats" / "G6C_REPRESENTATIVE_CASES.md"
G1A_PATH = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B_PATH = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"

# The three frozen role definitions - the complete case-selection
# contract, fixed before any source narrative was inspected.
ROLES = (
    {"role": "A",
     "label": "stable-but-confounded association illustration",
     "lane": "designed_contrast", "state_axis": "fed_policy_path",
     "subset": "all"},
    {"role": "B", "label": "fragile era-bounded secondary lens",
     "lane": "designed_contrast", "state_axis": "credit_hy_oas",
     "subset": "credit_available"},
    {"role": "C", "label": "broad null illustration",
     "lane": "frame_complete_historical", "state_axis": "fed_policy_path",
     "subset": "all"},
)

_ROLE_RECORD_LINE = {
    "A": "illustrates stable descriptive association (with unresolved "
         "calendar-time confounding)",
    "B": "illustrates fragility / era limitation",
    "C": "illustrates broad null or contradiction",
}

_CHAIN = {
    "fomc": "policy decision -> policy path / funding and curve "
            "conditions -> regional-bank equities -> KRE",
    "opec": "collective production policy -> crude supply expectations "
            "-> producer cash flows -> E&P equities -> XOP",
}


# ---------------------------------------------------------------------------
# Deterministic, outcome-blind selection
# ---------------------------------------------------------------------------


def role_universe(rows: Sequence[Mapping[str, Any]],
                  role: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out = [r for r in rows if r["denominator_ledger"] == role["lane"]]
    if role["subset"] == "credit_available":
        out = [r for r in out if r["credit_availability"] == "available"]
    return sorted(out, key=lambda r: r["candidate_id"])


def select_cases(rows) -> list[dict[str, Any]]:
    """The six frozen slots. Signature deliberately takes ONLY the
    promoted rows: no readout, return, or outcome object can reach
    selection."""
    slots: list[dict[str, Any]] = []
    for role in ROLES:
        universe = role_universe(rows, role)
        col = g6a._STATE_COLUMN[role["state_axis"]]
        xs = [float(r[col]) for r in universe]
        summary = g6a.five_number_summary(xs)  # frozen G6A convention
        for quantile, key in (("q25", "p25"), ("q75", "p75")):
            target = summary[key]
            best = min(universe,
                       key=lambda r: (abs(float(r[col]) - target),
                                      r["event_date"], r["candidate_id"]))
            slots.append({
                "role": role["role"], "label": role["label"],
                "lane": role["lane"], "state_axis": role["state_axis"],
                "quantile": quantile, "target": target,
                "candidate_id": best["candidate_id"],
                "event_date": best["event_date"],
                "state_value": float(best[col]),
                "distance": abs(float(best[col]) - target),
            })
    return slots


def unique_cases(slots: Sequence[Mapping[str, Any]]
                 ) -> list[dict[str, Any]]:
    """Selected candidates in first-appearance order, each carrying every
    role slot that chose it (duplicates preserved, rendered once)."""
    out: list[dict[str, Any]] = []
    for s in slots:
        entry = next((u for u in out
                      if u["candidate_id"] == s["candidate_id"]), None)
        if entry is None:
            entry = {"candidate_id": s["candidate_id"], "slots": []}
            out.append(entry)
        entry["slots"].append(f"{s['role']}/{s['quantile']}")
    return out


# ---------------------------------------------------------------------------
# G1 ledger provenance (existing pinned evidence only; no source hunting)
# ---------------------------------------------------------------------------


def g1a_case_info(text: str) -> dict[str, dict[str, str]]:
    info: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*`(fomc-policy-decision-\d{4}-\d{2}-\d{2})`",
                     line)
        if not m:
            continue
        cells = [c.strip() for c in line.split("|")]
        info[m.group(1)] = {"description": cells[5],
                            "source_ref": cells[6]}
    return info


def g1b_case_info(text: str) -> dict[str, dict[str, str]]:
    info: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not re.match(r"^\|\s*D\d{2}\s*\|", line):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 10 or cells[8].lower() not in ("canonical", "none"):
            continue
        ident = re.search(r"`([a-z0-9][a-z0-9-]+)`", cells[6])
        if ident:
            info[ident.group(1)] = {"description": cells[4],
                                    "source_ref": cells[3]}
    return info


def load_case_info() -> dict[str, dict[str, str]]:
    return {**g1a_case_info(G1A_PATH.read_text(encoding="utf-8")),
            **g1b_case_info(G1B_PATH.read_text(encoding="utf-8"))}


# ---------------------------------------------------------------------------
# Case interpretation notes (written for the deterministically selected
# cases; the renderer fails loudly if selection ever drifts away from them)
# ---------------------------------------------------------------------------

CASE_NOTES: dict[str, dict[str, str]] = {
    "opec-2024-11-03-one-month-delay": {
        "mechanism":
            "The V8 producers delayed the phased return of withheld "
            "supply by one further month, to end-December 2024 (source: "
            "the pinned V8 statement). Under the frozen chain, a delayed "
            "return is continued supply restraint: crude supply "
            "expectations tighten relative to the pre-announcement "
            "schedule, supporting producer cash-flow expectations and, "
            "second-order, E&P equities (XOP). The pre-event state is "
            "the deep-easing anchor of the OPEC lane, with the VIX "
            "percentile near the top of its historical range (values "
            "above).",
        "readout_comment":
            "The move is positive on every lens and every horizon and "
            "does not collapse after sector benchmarking, so it is not "
            "purely a broad-energy effect; standardized against the "
            "asset's own pre-event volatility it is visible at the "
            "one-day horizon and fades with distance.",
        "cannot_establish":
            "The decision is a scheduled item on the producers' "
            "calendar, so anticipation and any other information "
            "arriving inside the five- and twenty-day windows cannot be "
            "separated from the decision itself. The deep-easing state "
            "also sits late in the lane's calendar, so this case cannot "
            "separate the easing state from calendar position - the "
            "unresolved confound of its parent association (the lane's "
            "state-vs-date value is printed above).",
    },
    "opec-2023-11-30-voluntary-2p2": {
        "mechanism":
            "The 36th ONOMM and the accompanying coordinating-producers "
            "statement announced additional voluntary adjustments of "
            "about 2.2 mb/d for Q1 2024 (source: the pinned ONOMM "
            "release). Under the frozen chain an announced cut is supply "
            "restraint and would, taken at face value, support producer "
            "cash-flow expectations and XOP. The pre-event state is the "
            "lane's upper-quartile tightening anchor, with an inverted "
            "curve and the VIX percentile near its floor (values above).",
        "readout_comment":
            "Past the first day the traded outcome runs opposite the "
            "announcement's face-value direction on every benchmark: "
            "whatever the decision's nominal supply direction, the "
            "five-day window shows weakness against the market, the "
            "sector, and the asset's own volatility scale.",
        "cannot_establish":
            "This was a scheduled meeting announcing voluntary, "
            "member-level adjustments (per the pinned record), so "
            "anticipation and post-announcement repositioning cannot be "
            "separated from the decision's content in a single case. The "
            "tightening state co-occurs with one segment of the "
            "calendar, so era effects and state effects are "
            "indistinguishable here - the same confound its parent "
            "association carries.",
    },
    "opec-2025-09-07-oct-137k": {
        "mechanism":
            "The V8 statement raised the October 2025 production level "
            "by 0.137 mb/d, the first step of returning the separate "
            "1.65 mb/d voluntary layer (source: the pinned V8 release). "
            "Under the frozen chain an announced supply increase "
            "pressures crude supply expectations and producer cash "
            "flows. The pre-event credit state is the lower-quartile "
            "anchor of the era-bounded subset: a tight high-yield "
            "spread (value above).",
        "readout_comment":
            "The immediate response is mildly negative and consistent "
            "across lenses; the raw twenty-day gain does not survive "
            "the market benchmark, so it reads as broad market "
            "participation rather than an asset-specific response, and "
            "no standardized move is large on the asset's own "
            "volatility scale.",
        "cannot_establish":
            "A tight credit spread in this subset is largely a property "
            "of when the event happened: the credit level tracks "
            "calendar time inside the surviving window (the subset's "
            "state-vs-date value is printed above), and the subset is "
            "era-bounded and small. Most of the credit associations "
            "flip sign under leave-one-out (counts above), so no single "
            "case in this lens - including this one - supports any "
            "state-conditional reading beyond illustration.",
    },
    "opec-2024-03-03-q2-extension": {
        "mechanism":
            "The coordinating-producers statement extended the 2.2 mb/d "
            "voluntary adjustments through Q2 2024 (source: the pinned "
            "opec.org release). Under the frozen chain an extension of "
            "cuts is continued restraint. The pre-event credit state is "
            "the upper-quartile anchor of the era-bounded subset - the "
            "wider end of a narrow, tight-spread era - with an inverted "
            "curve (values above).",
        "readout_comment":
            "The large raw twenty-day gain survives the market "
            "benchmark but collapses to almost nothing after sector "
            "benchmarking - the lens hierarchy doing exactly the work "
            "it was designed for: a sector-wide energy move, not an "
            "asset-specific one.",
        "cannot_establish":
            "The case cannot attribute the twenty-day sector-wide oil "
            "move to this scheduled extension, and the era-bounded "
            "credit subset cannot support any conditional claim about "
            "spread levels (its size, era bound, and state-vs-date "
            "value are printed above). The case illustrates the "
            "fragility documented in G6B rather than escaping it.",
    },
    "fomc-policy-decision-2019-09-18": {
        "mechanism":
            "The FOMC lowered the target range to 1.75-2.00 percent "
            "(source: the pinned Fed statement), the mid-cycle easing "
            "anchor of the frame. Under the frozen chain a policy-path "
            "change transmits through funding and curve conditions to "
            "regional-bank equities (KRE).",
        "readout_comment":
            "The readout is small and negative on every lens and every "
            "horizon, and muted relative to the asset's own pre-event "
            "volatility; against the market, the financial sector, or "
            "its own volatility scale, KRE's response to a realized "
            "rate cut is quiet.",
        "cannot_establish":
            "This was a scheduled decision, anticipated in the sense of "
            "the anchor-quality label the whole frame carries, so the "
            "muted response cannot distinguish 'no transmission' from "
            "'already priced'. KRE is one predeclared second-order "
            "lens, not the complete market reaction to monetary policy "
            "- a flat KRE readout is not a flat monetary event.",
    },
    "fomc-policy-decision-2018-05-02": {
        "mechanism":
            "The FOMC maintained the target range at 1.50-1.75 percent "
            "(source: the pinned Fed statement). The case anchors the "
            "frame's upper-quartile tightening state: the STATE "
            "reflects the hiking path into the meeting, while the "
            "decision itself was a hold - a useful reminder that the "
            "state axis describes pre-event posture, not the decision's "
            "content.",
        "readout_comment":
            "The hierarchy is small and direction-unstable: no lens "
            "holds one sign across the three horizons - the shape of "
            "the broad FOMC null in one dossier.",
        "cannot_establish":
            "A scheduled hold cannot isolate decision content from "
            "prior expectations and accompanying communication; this "
            "case illustrates only the observed KRE readout under the "
            "frozen pre-event state. It is one draw from a lane whose "
            "associations are flat and sign-unstable under "
            "leave-one-out stress (the lane board above).",
    },
}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _f(x) -> str:
    return "n/a" if x is None else f"{x:+.4f}"


def _fmt_pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:+.2f}%"


def render_case_readout(metrics: Mapping[str, Mapping[int, float]]) -> str:
    """The numeric readout narrative, generated ENTIRELY from the supplied
    case readout: humans author interpretation; code supplies every
    computed numeric fact."""
    a, s, x, z = (metrics["absolute_asset_return"],
                  metrics["spy_relative_ar"],
                  metrics["sector_relative_ar"], metrics["sar"])
    peak = max(g6a.HORIZONS, key=lambda h: (abs(z[h]), -h))
    return (
        f"Absolute asset return: {_fmt_pct(a[1])} at 1d, {_fmt_pct(a[5])} "
        f"at 5d, {_fmt_pct(a[20])} at 20d. "
        f"Against SPY: {_fmt_pct(s[1])} / {_fmt_pct(s[5])} / "
        f"{_fmt_pct(s[20])}. "
        f"Against the sector benchmark: {_fmt_pct(x[1])} / "
        f"{_fmt_pct(x[5])} / {_fmt_pct(x[20])}. "
        f"Standardized (SAR): {z[1]:+.2f} / {z[5]:+.2f} / {z[20]:+.2f}; "
        f"the largest standardized move is {z[peak]:+.2f} at {peak}d.")


def _case_metric_table(metrics: Mapping[str, Mapping[int, float]]
                       ) -> list[str]:
    L = ["| metric | 1d | 5d | 20d |", "|---|---|---|---|"]
    for metric in g6a.METRICS:
        vals = metrics[metric]
        if metric == "sar":
            cells = [f"{vals[h]:+.2f}" for h in g6a.HORIZONS]
        else:
            cells = [_fmt_pct(vals[h]) for h in g6a.HORIZONS]
        L.append(f"| {g6a._METRIC_LABEL[metric]} | " + " | ".join(cells)
                 + " |")
    return L


def _role_context_lines(role: str, boards: Mapping[str, Any]) -> list[str]:
    cont = boards["continuous"]
    conf = {(b["lane"], b["state_axis"]): b["rho_state_vs_date_ordinal"]
            for b in boards["confound"]}
    if role == "A":
        rows = [b for b in cont if b["lane"] == "designed_contrast"
                and b["state_axis"] == "fed_policy_path"
                and b["metric"] == "sector_relative_ar"]
        L = ["Parent-surface context (Role A, from the G6B board - "
             "sector-relative AR, the association under scrutiny):"]
        for b in rows:
            L.append(f"- {b['horizon']}d: rho {_f(b['rho'])}; LOEO range "
                     f"[{_f(b['loeo']['min'])}, {_f(b['loeo']['max'])}] "
                     f"({b['loeo']['opposite_sign']} sign reversals); "
                     f"LOYO range [{_f(b['loyo']['min'])}, "
                     f"{_f(b['loyo']['max'])}] "
                     f"({b['loyo']['opposite_sign']} reversals)")
        L.append(f"- state-vs-date rho (OPEC lane): "
                 f"{_f(conf[('designed_contrast', 'fed_policy_path')])} - "
                 "the calendar-time confound remains unresolved")
        return L
    if role == "B":
        rows = [b for b in cont if b["lane"] == "designed_contrast"
                and b["state_axis"] == "credit_hy_oas"
                and b["horizon"] == 5
                and b["metric"] in ("spy_relative_ar", "sar")]
        L = ["Parent-surface context (Role B): N=16, era-bounded "
             "(2023-07-04 onward), secondary-only lens."]
        for b in rows:
            L.append(f"- {b['metric']} 5d: rho {_f(b['rho'])}; LOEO "
                     f"[{_f(b['loeo']['min'])}, {_f(b['loeo']['max'])}]; "
                     f"LOYO [{_f(b['loyo']['min'])}, "
                     f"{_f(b['loyo']['max'])}]")
        credit_rows = [b for b in cont
                       if b["lane"] == "designed_contrast"
                       and b["state_axis"] == "credit_hy_oas"]
        stable = sorted(f"{b['metric']} {b['horizon']}d"
                        for b in credit_rows
                        if b["loeo"]["opposite_sign"] == 0
                        and b["loyo"]["opposite_sign"] == 0)
        L.append(f"- {12 - len(stable)} of the 12 credit associations "
                 "flip sign under leave-one-out; reversal-free: "
                 + ", ".join(stable))
        L.append(f"- credit-vs-date rho (OPEC lane): "
                 f"{_f(conf[('designed_contrast', 'credit_hy_oas')])} - "
                 "the credit level itself tracks calendar time inside the "
                 "surviving window")
        return L
    frame = [b for b in cont
             if b["lane"] == "frame_complete_historical"
             and b["rho"] is not None]
    max_abs = max(abs(b["rho"]) for b in frame)
    n_loeo = sum(1 for b in frame if b["loeo"]["opposite_sign"] > 0)
    n_loyo = sum(1 for b in frame if b["loyo"]["opposite_sign"] > 0)
    return [
        "Parent-surface context (Role C, the FOMC frame lane):",
        f"- largest absolute full-sample rho anywhere in the lane: "
        f"{max_abs:.4f}",
        f"- of the lane's 60 associations, {n_loeo} flip sign under "
        f"leave-one-event-out and {n_loyo} under leave-one-year-out",
        f"- state-vs-date rho (fed_policy_path, FOMC lane): "
        f"{_f(conf[('frame_complete_historical', 'fed_policy_path')])}",
        "- this breadth of flatness and instability is the null result "
        "the case below illustrates",
    ]


def build_report_text() -> str:
    rows = g6a.load_promoted_rows()
    g6a.reconcile_universe(rows)
    slots = select_cases(rows)
    uniq = unique_cases(slots)
    readouts = g6a.compute_readouts(rows)
    boards = g6b.build_boards(rows, readouts)
    info = load_case_info()
    by_id = {r["candidate_id"]: r for r in rows}

    L = [
        "# G6C representative cases (Mission G, g0-v1)",
        "",
        f"Version: `{VERSION}`.",
        "",
        "## Case-selection contract",
        "",
        "- Disclosed as post-readout selection: this slice ran after "
        "the G6A outcomes and G6B diagnostics existed. The defense against "
        "cherry-picking is mechanical: outcome magnitude was not used - "
        "cases are anchored to STATE quantiles, the selector receives no "
        "outcome object (tested), and perturbing outcome values cannot "
        "change the selected ids (tested).",
        "- Three frozen roles, six slots: Role A - "
        "stable-but-confounded association illustration (OPEC lane, "
        "fed_policy_path, all 32 designed rows); Role B - fragile "
        "era-bounded secondary lens (OPEC lane, credit_hy_oas, the "
        "16-row credit-available subset); Role C - broad null "
        "illustration (FOMC frame lane, fed_policy_path, all 65 rows). "
        "Each role selects its Q25 and Q75 state-anchor case.",
        "- Anchors use the G6A inclusive quantile convention; selection "
        "minimizes |state - target| with ties broken by event date "
        "ascending, then candidate id ascending. No manual override, no "
        "largest-return path, no famous-event path; duplicate role "
        "selections are preserved and rendered once.",
        "- Representative cases are illustrations, never proof.",
        "",
        "## Six-slot selection ledger",
        "",
        "| role | lane | axis | quantile | target | selected candidate | "
        "state | distance |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in slots:
        L.append(f"| {s['role']} ({s['label']}) | {s['lane']} | "
                 f"`{s['state_axis']}` | {s['quantile'].upper()} | "
                 f"{_f(s['target'])} | `{s['candidate_id']}` | "
                 f"{_f(s['state_value'])} | {s['distance']:.4f} |")
    dups = [u for u in uniq if len(u["slots"]) > 1]
    L.append("")
    L.append(f"Six role slots resolve to {len(uniq)} unique cases"
             + ("; duplicate-role overlaps: "
                + "; ".join(f"`{d['candidate_id']}` holds "
                            f"{', '.join(d['slots'])}" for d in dups)
                if dups else "; no candidate serves two roles") + ".")
    L += ["", "## Representative case dossiers", ""]
    for u in uniq:
        cid = u["candidate_id"]
        r = by_id[cid]
        note = CASE_NOTES.get(cid)
        if note is None:
            raise ValueError(
                f"no interpretation note exists for selected case {cid!r};"
                " selection has drifted - re-review before rendering")
        case_slots = [s for s in slots if s["candidate_id"] == cid]
        fam = r["sampling_family"]
        L.append(f"### `{cid}`")
        L.append("")
        L.append(f"Role slots: " + ", ".join(
            f"{s['role']}/{s['quantile'].upper()} (target "
            f"{_f(s['target'])}, state {_f(s['state_value'])})"
            for s in case_slots))
        L.append("")
        L.append(f"- event date: {r['event_date']} | lane: "
                 f"{r['denominator_ledger']} | family: {fam}")
        L.append(f"- source (G1 ledger): {info[cid]['source_ref']}")
        L.append(f"- source-native description: {info[cid]['description']}")
        L.append(f"- frozen transmission hypothesis: {_CHAIN[fam]}")
        L.append(f"- assets: primary {r['primary_asset']}, market "
                 f"benchmark {r['market_benchmark']}, sector benchmark "
                 f"{r['sector_benchmark']}")
        L.append("")
        credit = (_f(r["state_credit_hy_oas"])
                  if r["state_credit_hy_oas"] is not None
                  else "source_missing (pre-window)")
        L.append(f"Pre-event state (cutoff {r['cutoff']}): fed policy "
                 f"path {_f(r['state_fed_policy_path'])} "
                 f"({r['tag_fed_policy_path']}); VIX percentile "
                 f"{_f(r['state_vix_level_percentile'])}; SPY vs MA200 "
                 f"{_f(r['state_spy_trend_ma200'])} "
                 f"({r['tag_spy_trend_ma200']}); 2s10s "
                 f"{_f(r['state_curve_2s10s'])} ({r['tag_curve_2s10s']}); "
                 f"HY OAS {credit}.")
        L.append("")
        L += _case_metric_table(readouts[cid]["metrics"])
        L.append("")
        for role in sorted({s["role"] for s in case_slots}):
            L += _role_context_lines(role, boards)
            L.append("")
        L.append("#### Event and transmission mechanism")
        L.append("")
        L.append(note["mechanism"])
        L.append("")
        L.append("#### What the market readout shows")
        L.append("")
        L.append(render_case_readout(readouts[cid]["metrics"]))
        L.append("")
        L.append(note["readout_comment"])
        L.append("")
        L.append("#### What this case cannot establish")
        L.append("")
        L.append(note["cannot_establish"])
        L.append("")
        L.append("#### Role in the research record")
        L.append("")
        L.append("; ".join(sorted({_ROLE_RECORD_LINE[s["role"]]
                                   for s in case_slots})) + ".")
        L.append("")
    L += [
        "## Cross-case synthesis",
        "",
        "All four Mission G research outcomes stand together; none is "
        "traded away for a cleaner story:",
        "",
        "1. Broad historical state conditioning is mostly flat, fragile, "
        "or contradictory: 44 of 120 continuous associations flip sign "
        "when one event is removed, 76 of 120 when one calendar year is "
        "removed (G6B).",
        "2. The OPEC fed_policy_path x sector-relative AR pattern is a "
        "stable descriptive association with unresolved calendar-time "
        "confounding: no leave-one-out check flips it, and the state's "
        "own correlation with calendar time (-0.27) means these data "
        "cannot separate the two.",
        "3. Credit evidence is narrow, era-bounded, and mostly fragile: "
        "9 of its 12 OPEC-lane associations flip sign under "
        "leave-one-out, and the credit level itself tracks calendar time "
        "(-0.45 OPEC / -0.73 FOMC) inside the surviving window.",
        "4. Representative cases neither rescue nor overturn the "
        "aggregate surface: they are quantile-anchored illustrations of "
        "what the boards already say, selected without outcome values.",
        "",
        "## Rejected interpretations",
        "",
        "- Broad regime prediction from the historical state vector: "
        "rejected - the surface is predominantly flat and unstable.",
        "- A causal Fed effect on OPEC-event transmission: rejected - "
        "the association is descriptive, one lane, N=32, and the "
        "calendar-time confound is unresolved; the frozen wording is "
        "'stable descriptive association with unresolved calendar-time "
        "confounding'.",
        "- Credit as a primary cross-period state variable: rejected - "
        "era-bounded coverage (36/97) with strong calendar tracking; "
        "surviving two 5d stability checks does not promote it.",
        "- Single-case confirmation: rejected - cases are illustrations, "
        "never proof.",
        "- Thin-cell inference: rejected - `insufficient_n` cells remain "
        "descriptive display only.",
        "- The FOMC flat surface as absence of substance: rejected - it "
        "is a substantive null result of a frame-complete lane under a "
        "frozen manifest.",
        "",
        "## Non-claims",
        "",
        "Descriptive illustration only. No causal regime effect, no "
        "forecast, no trading recommendation, no significance claim, no "
        "prevalence claim for designed-contrast evidence. Not a trading, "
        "prediction, or recommendation surface.",
        "",
        "## Reproduction",
        "",
        "```",
        "python scripts/g6c_representative_cases.py --emit",
        "python -m unittest tests.test_g6c_representative_cases",
        "```",
    ]
    return "\n".join(L) + "\n"


def emit_report() -> str:
    text = build_report_text()
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    return f"G6C report written -> {REPORT_PATH.relative_to(ROOT)}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G6C representative cases (outcome-blind selection).")
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args(argv)
    if args.select:
        rows = g6a.load_promoted_rows()
        print(json.dumps(select_cases(rows), indent=1, sort_keys=True))
    if args.emit:
        print(emit_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""J3 - frozen mechanism and transmission readout (Mission J, j0-v1).

Contract ``j3-mechanism-readout-v1``. J3 is a READOUT layer: it consumes
the published, tracked J1B and J2 result surfaces and mechanically applies
the frozen J0 node / panel / modifier / edge-state rules (J0 sections 5,
6, 7, 12, 13). It computes NO statistic of any kind: no response value,
no median-of-percentiles estimand, no placement calibration, no event
subset, no return, no beta, and no test quantity. If reaching an edge
conclusion would require a new statistic, the edge is MEASUREMENT
UNRESOLVED - the statistic is never invented.

The adjudicator is pure and deterministic. The only inputs are the two
tracked Markdown reports (parsed fail-loud, read-only) and the frozen
graph manifest below. The report renderer is deterministic, shows every
node, panel member, edge, and denominator, never ranks, and uses only the
frozen vocabulary.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

J3_CONTRACT = "j3-mechanism-readout-v1"

J1B_REPORT_PATH = ROOT / "stats" / "J1B_FOMC_ROBUSTNESS_RESULTS.md"
J2_REPORT_PATH = ROOT / "stats" / "J2_TIMING_COLLISION_RESULTS.md"
REPORT_PATH = ROOT / "stats" / "J3_MECHANISM_TRANSMISSION_READOUT.md"

PRERUN_GATE_BANNER = ("J3 PRE-RUN GATE PASSED — FROZEN MECHANISM READOUT "
                      "AUTHORIZED")

# The frozen five-state edge enumeration (J0 section 5). No sixth state.
EDGE_STATES: tuple[str, ...] = (
    "PROPAGATED", "TRANSMISSION BREAK", "UPSTREAM NOT ACTIVATED",
    "DOWNSTREAM WITHOUT UPSTREAM", "MEASUREMENT UNRESOLVED")

NODE_READINGS: tuple[str, ...] = ("ACTIVATED", "NOT ACTIVATED",
                                  "UNRESOLVED")

CONTEXTUAL_MEASUREMENT = "2S10S_CMT"  # J0 section 12.2: context, not a node
CONTEXT_BENCHMARK = "SPY"             # J0 section 12.1 N4: context only

# ---------------------------------------------------------------------------
# Frozen graph manifest (J0 sections 12.1 / 12.3) - no node may be added
# or removed after J1/J2 results are visible.
# ---------------------------------------------------------------------------

GRAPH_NODES: tuple[dict[str, Any], ...] = (
    {"node": "N0", "role": "fomc_decision",
     "panel": (), "primary": None, "m_class": None,
     "route_b_members": (),
     "note": "event trigger; activation definitional (the decision "
             "occurred); no market claim"},
    {"node": "N1", "role": "policy_rates_repricing",
     "panel": ("2Y_CMT", "SHY"), "primary": "2Y_CMT",
     "m_class": "M2", "alternate_m_class": {"SHY": "M3"},
     "route_b_members": (),  # only one M3 alternate exists; Route B is
                             # structurally unavailable on this panel
     "note": "measurement-limited: the ideal M1 policy-repricing measure "
             "(fed funds futures / OIS) is unavailable; the 2Y CMT blends "
             "policy expectations with term premium (J0 section 8)"},
    {"node": "N2", "role": "balance_sheet_sensitive_second_order",
     "panel": ("KRE", "IAT", "KBE"), "primary": "KRE",
     "m_class": "M3", "alternate_m_class": {"IAT": "M3", "KBE": "M3"},
     "route_b_members": ("KRE", "IAT", "KBE"),
     "note": "equity-proxy limits (fund mechanics); single-proxy results "
             "stay asset-specific"},
    {"node": "N3", "role": "broad_financial_sector",
     "panel": ("XLF", "VFH"), "primary": "XLF",
     "m_class": "M3", "alternate_m_class": {"VFH": "M3"},
     "route_b_members": ("XLF", "VFH"),
     "note": "sector ETFs are cap-weighted composites; not a statement "
             "about every financial firm"},
)

GRAPH_EDGES: tuple[dict[str, str], ...] = (
    {"edge": "E1", "upstream": "fomc_decision",
     "downstream": "policy_rates_repricing",
     "upstream_kind": "definitional"},
    {"edge": "E2", "upstream": "policy_rates_repricing",
     "downstream": "balance_sheet_sensitive_second_order",
     "upstream_kind": "measured"},
    {"edge": "E3", "upstream": "balance_sheet_sensitive_second_order",
     "downstream": "broad_financial_sector",
     "upstream_kind": "measured"},
)

_STATE_A = "ELEVATED"
_STATES_BC = ("ORDINARY_UNRESOLVED", "LOWER_MAGNITUDE")
_STATE_D = "DISCORDANT"
_CORROBORATED = ("ROLE-CONSISTENT", "BROAD MEASUREMENT CONSISTENCY")

TIMING_QUALIFIER_SENTENCE = ("timing evidence is lens-dependent under "
                             "daily measurement")


class J3ParseError(RuntimeError):
    """A tracked published report could not be parsed - refuse."""


class J3ReconciliationError(RuntimeError):
    """The published surface differs from the frozen expectation - refuse."""


# ---------------------------------------------------------------------------
# Fail-loud parsers over the tracked published reports (read-only)
# ---------------------------------------------------------------------------

_J1B_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(M\d)\s*\|"
    r"([^|]+)\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)\s*\|"
    r"\s*([0-9.]+)\s*\|\s*([A-Z_]+)\s*\|\s*$")

_J2_ROW = re.compile(
    r"^\|\s*(1[3-6])\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*\[([-0-9]+),\s*"
    r"([-0-9]+)\]\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)"
    r"\s*\|\s*([0-9.]+)\s*\|\s*([A-Z_]+)\s*\|\s*$")

_OVERLAY_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\d+/\d+)\s*\|\s*(\d+/\d+)\s*\|")

_PANEL_HEADER = re.compile(r"^### (\w+)\s*$")
_PANEL_MEMBERS = re.compile(
    r"^- members: ([^(]+) \(primary: (\S+)\)\s*$")
_PANEL_STATE = re.compile(r"^- (\S+): ([A-Z_]+)\s*$")
_PANEL_MODIFIER = re.compile(r"^- role modifier: \*\*([A-Z -]+)\*\*\s*$")


def parse_j1b_report(text: str) -> dict[str, Any]:
    """Parse the tracked J1B 12-cell surface, overlays, and panels."""
    cells: dict[int, dict[str, str]] = {}
    overlays: dict[int, dict[str, str]] = {}
    for line in text.splitlines():
        m = _J1B_ROW.match(line.strip())
        if m:
            cells[int(m.group(1))] = {
                "measurement": m.group(2), "lens": m.group(3),
                "role": m.group(4), "m_class": m.group(5),
                "evidence_class": m.group(6).strip(),
                "available": m.group(7), "attempted": m.group(8),
                "reference_n": m.group(9), "memp": m.group(10),
                "calib": m.group(11), "state": m.group(12)}
            continue
        m = _OVERLAY_ROW.match(line.strip())
        if m and int(m.group(1)) in cells and int(m.group(1)) not in overlays:
            overlays[int(m.group(1))] = {"loyo": m.group(3),
                                         "loeo": m.group(4)}
    if sorted(cells) != list(range(1, 13)):
        raise J3ParseError(
            f"J1B table parsed cells {sorted(cells)}, expected 1..12")

    panels: dict[str, dict[str, Any]] = {}
    section = text.split("## Role-level panel summaries", 1)
    if len(section) != 2:
        raise J3ParseError("J1B panel summaries section not found")
    current: Optional[str] = None
    for line in section[1].splitlines():
        line = line.strip()
        m = _PANEL_HEADER.match(line)
        if m:
            current = m.group(1)
            panels[current] = {"members": [], "primary": None,
                               "states": {}, "modifier": None}
            continue
        if current is None:
            continue
        m = _PANEL_MEMBERS.match(line)
        if m:
            panels[current]["members"] = [
                s.strip() for s in m.group(1).split(",")]
            panels[current]["primary"] = m.group(2)
            continue
        m = _PANEL_MODIFIER.match(line)
        if m:
            panels[current]["modifier"] = m.group(1)
            continue
        m = _PANEL_STATE.match(line)
        if m and m.group(1) in panels[current]["members"]:
            panels[current]["states"][m.group(1)] = m.group(2)
        if line.startswith("## "):
            current = None
    for role, p in panels.items():
        if not p["members"] or p["modifier"] is None or not p["states"]:
            raise J3ParseError(f"J1B panel {role} incompletely parsed")
    m = re.search(r"^- 2S10S_CMT: \*\*([A-Z_]+)\*\*", text, re.M)
    if not m:
        raise J3ParseError("J1B contextual 2s10s state not found")
    return {"cells": cells, "overlays": overlays, "panels": panels,
            "contextual_state": m.group(1)}


def parse_j2_report(text: str) -> dict[str, Any]:
    """Parse the tracked J2 timing surface, overlays, and collision facts."""
    cells: dict[int, dict[str, str]] = {}
    overlays: dict[int, dict[str, str]] = {}
    for line in text.splitlines():
        m = _J2_ROW.match(line.strip())
        if m:
            cells[int(m.group(1))] = {
                "measurement": m.group(2), "metric": m.group(3),
                "window": f"[{m.group(4)}, {m.group(5)}]",
                "available": m.group(6), "attempted": m.group(7),
                "reference_n": m.group(8), "memp": m.group(9),
                "calib": m.group(10), "state": m.group(11)}
            continue
        m = _OVERLAY_ROW.match(line.strip())
        if m and int(m.group(1)) in cells and int(m.group(1)) not in overlays:
            overlays[int(m.group(1))] = {"loyo": m.group(3),
                                         "loeo": m.group(4)}
    if sorted(cells) != [13, 14, 15, 16]:
        raise J3ParseError(
            f"J2 table parsed cells {sorted(cells)}, expected 13..16")

    c1_m = re.search(
        r"^- C1 families 2-3 - BLS CPI and BLS Employment Situation: "
        r"\*\*(unadjudicable[^*]*)\*\*", text, re.M)
    c2_m = re.search(
        r"^- C2 - cross-channel compound events: the tracked "
        r"`(opec-known-date-exclusion-register@\S+)` \((\d+) calendar "
        r"dates\) yields \*\*(\d+)\*\* tagged FOMC event", text, re.M)
    self_m = re.search(r"minimum anchor spacing (\d+) sessions; "
                       r"(\d+) violations", text)
    all_m = re.search(r"^- \*\*all\*\*: exact N = (\d+)\.", text, re.M)
    free_m = re.search(r"^- \*\*collision_free\*\*: exact N = (\d+)",
                       text, re.M)
    c2n_m = re.search(r"^- \*\*c2_tagged\*\*: exact N = (\d+)\.", text,
                      re.M)
    withdraw_m = re.search(
        r"section-15 withdrawal condition for the 1d concentration claim "
        r"is\s+not triggered", text)
    for name, m in (("C1", c1_m), ("C2", c2_m), ("FOMC-self", self_m),
                    ("all-N", all_m), ("collision-free-N", free_m),
                    ("c2-N", c2n_m), ("withdrawal", withdraw_m)):
        if not m:
            raise J3ParseError(f"J2 collision/timing marker {name} "
                               "not found")
    return {
        "timing_cells": cells,
        "overlays": overlays,
        "collisions": {
            "c1_adjudicable": False,
            "c1_line": c1_m.group(1).strip(),
            "c2_register": c2_m.group(1),
            "c2_register_dates": int(c2_m.group(2)),
            "c2_tagged_n": int(c2_m.group(3)),
            "fomc_self_min_spacing": int(self_m.group(1)),
            "fomc_self_violations": int(self_m.group(2)),
            "all_n": int(all_m.group(1)),
            "collision_free_n": int(free_m.group(1)),
            "c2_subset_n": int(c2n_m.group(1)),
        },
        "withdrawal_condition_triggered": False,
    }


def load_published_surfaces(*, j1b_path: Path = J1B_REPORT_PATH,
                            j2_path: Path = J2_REPORT_PATH
                            ) -> dict[str, Any]:
    return {"j1b": parse_j1b_report(j1b_path.read_text(encoding="utf-8")),
            "j2": parse_j2_report(j2_path.read_text(encoding="utf-8"))}


# ---------------------------------------------------------------------------
# Pure frozen adjudicator (J0 sections 5 and 7, verbatim rule paths)
# ---------------------------------------------------------------------------


def role_reading(*, primary_state: str, primary_m_class: str,
                 primary_usable: bool, modifier: str) -> dict[str, str]:
    """The frozen three-valued upstream/role reading (J0 section 5)."""
    if not primary_usable:
        return {"reading": "UNRESOLVED", "m_class": primary_m_class,
                "rule_path": ("primary unusable at run time -> UNRESOLVED; "
                              "no alternate may replace the frozen primary "
                              "(J0 section 6.4, no proxy rescue)")}
    if primary_state == _STATE_D:
        return {"reading": "UNRESOLVED", "m_class": primary_m_class,
                "rule_path": "primary State D -> UNRESOLVED (J0 section 5)"}
    if primary_state in _STATES_BC:
        return {"reading": "NOT ACTIVATED", "m_class": primary_m_class,
                "rule_path": f"primary State B/C ({primary_state}) -> "
                             "NOT ACTIVATED (J0 section 5)"}
    if primary_state == _STATE_A:
        if primary_m_class in ("M1", "M2"):
            return {"reading": "ACTIVATED", "m_class": primary_m_class,
                    "rule_path": (f"usable {primary_m_class} primary at "
                                  "State A stands alone -> ACTIVATED "
                                  "(J0 section 5)")}
        if modifier in _CORROBORATED:
            return {"reading": "ACTIVATED", "m_class": primary_m_class,
                    "rule_path": ("M3 primary at State A with role "
                                  f"{modifier} (>= ROLE-CONSISTENT) -> "
                                  "ACTIVATED (J0 section 5 corroboration "
                                  "rule)")}
        return {"reading": "UNRESOLVED", "m_class": primary_m_class,
                "rule_path": ("M3 primary at State A WITHOUT the "
                              "ROLE-CONSISTENT modifier -> UNRESOLVED "
                              "(measurement-corroboration failure, "
                              "J0 section 5)")}
    raise ValueError(f"unknown node state {primary_state!r}")


def edge_state(upstream_reading: str,
               downstream: Mapping[str, Any]) -> dict[str, str]:
    """The frozen ordered edge precedence (J0 section 5, exact order).

    ``downstream`` carries: primary_state, primary_m_class,
    primary_usable, modifier, route_b_satisfied.
    """
    if upstream_reading not in NODE_READINGS:
        raise ValueError(f"unknown upstream reading {upstream_reading!r}")
    st = downstream["primary_state"]
    mc = downstream["primary_m_class"]
    usable = bool(downstream["primary_usable"])
    modifier = downstream["modifier"]
    route_b = bool(downstream.get("route_b_satisfied"))

    # Precedence step 1: upstream UNRESOLVED -> MEASUREMENT UNRESOLVED.
    if upstream_reading == "UNRESOLVED":
        return {"state": "MEASUREMENT UNRESOLVED",
                "rule_path": ("precedence step 1: upstream reading "
                              "UNRESOLVED -> MEASUREMENT UNRESOLVED "
                              "regardless of downstream (J0 section 5)")}

    # Precedence step 2: downstream cannot support the edge-level claim.
    if not usable:
        return {"state": "MEASUREMENT UNRESOLVED",
                "rule_path": ("precedence step 2: downstream primary "
                              "unusable -> MEASUREMENT UNRESOLVED "
                              "regardless of upstream (J0 section 5)")}
    if st == _STATE_D:
        return {"state": "MEASUREMENT UNRESOLVED",
                "rule_path": ("precedence step 2: downstream primary "
                              "State D -> MEASUREMENT UNRESOLVED "
                              "regardless of upstream (J0 section 5)")}
    if st == _STATE_A and mc == "M3" and modifier not in _CORROBORATED:
        return {"state": "MEASUREMENT UNRESOLVED",
                "rule_path": ("precedence step 2, measurement-governance "
                              "gate: M3 downstream primary at State A "
                              "with the role below ROLE-CONSISTENT - a "
                              "single elevated M3 proxy cannot support "
                              "the elevated edge claim, regardless of "
                              "upstream (J0 sections 5 and 7); the "
                              "proxy-specific elevation stays visible at "
                              "node level")}
    if (st in _STATES_BC and mc == "M3" and not route_b
            and upstream_reading == "ACTIVATED"):
        return {"state": "MEASUREMENT UNRESOLVED",
                "rule_path": ("precedence step 2, measurement-governance "
                              "gate: a break claim is considered "
                              "(upstream ACTIVATED) but the M3 "
                              "non-response lacks Route B support (two "
                              "design-distinct M3 measurements agreeing) "
                              "-> MEASUREMENT UNRESOLVED, never "
                              "TRANSMISSION BREAK (J0 section 7)")}

    # Precedence step 3: adjudicate the remaining cases.
    if upstream_reading == "ACTIVATED":
        if st == _STATE_A:
            support = ("usable M1/M2 primary stands alone (Route A)"
                       if mc in ("M1", "M2") else
                       f"M3 primary with role {modifier} "
                       "(>= ROLE-CONSISTENT)")
            return {"state": "PROPAGATED",
                    "rule_path": ("precedence step 3: upstream ACTIVATED "
                                  "and downstream supports the ELEVATED "
                                  f"edge claim ({support}) -> PROPAGATED "
                                  "(J0 section 5)")}
        support = ("usable M1/M2 primary (Route A)" if mc in ("M1", "M2")
                   else "Route B satisfied (design-distinct M3 agreement)")
        return {"state": "TRANSMISSION BREAK",
                "rule_path": ("precedence step 3: upstream ACTIVATED and "
                              "downstream supports the NON-RESPONSE edge "
                              f"claim ({support}) -> TRANSMISSION BREAK "
                              "(J0 section 5)")}
    # upstream NOT ACTIVATED
    if st == _STATE_A:
        support = ("usable M1/M2 primary stands alone (Route A)"
                   if mc in ("M1", "M2") else
                   f"M3 primary with role {modifier} (>= ROLE-CONSISTENT)")
        return {"state": "DOWNSTREAM WITHOUT UPSTREAM",
                "rule_path": ("precedence step 3: upstream NOT ACTIVATED "
                              "and downstream supports the ELEVATED edge "
                              f"claim ({support}) -> DOWNSTREAM WITHOUT "
                              "UPSTREAM (J0 section 5)")}
    return {"state": "UPSTREAM NOT ACTIVATED",
            "rule_path": ("precedence step 3: upstream NOT ACTIVATED and "
                          "downstream primary State B/C - no break claim "
                          "is considered, so Route B support is not "
                          "required -> UPSTREAM NOT ACTIVATED "
                          "(J0 section 5)")}


# ---------------------------------------------------------------------------
# Reconciliation gate (fail if the published surface differs)
# ---------------------------------------------------------------------------

_EXPECTED_PANELS = {
    "policy_rates_repricing": ["2Y_CMT", "SHY"],
    "balance_sheet_sensitive_second_order": ["KRE", "IAT", "KBE"],
    "broad_financial_sector": ["XLF", "VFH"],
}


def reconcile_published_evidence(surfaces: Mapping[str, Any]) -> None:
    j1b, j2 = surfaces["j1b"], surfaces["j2"]
    for no, c in j1b["cells"].items():
        if c["state"] != "ELEVATED":
            raise J3ReconciliationError(
                f"published J1B cell {no} is {c['state']}, expected the "
                "tracked ELEVATED surface - refusing")
    for role, members in _EXPECTED_PANELS.items():
        p = j1b["panels"].get(role)
        if p is None or p["members"] != members:
            raise J3ReconciliationError(
                f"published J1B panel {role} members differ - refusing")
        if p["modifier"] != "BROAD MEASUREMENT CONSISTENCY":
            raise J3ReconciliationError(
                f"published J1B panel {role} modifier {p['modifier']!r} "
                "differs from the tracked surface - refusing")
    expected_j2 = {13: "ORDINARY_UNRESOLVED", 14: "ORDINARY_UNRESOLVED",
                   15: "ELEVATED", 16: "ELEVATED"}
    for no, want in expected_j2.items():
        got = j2["timing_cells"][no]["state"]
        if got != want:
            raise J3ReconciliationError(
                f"published J2 cell {no} is {got}, expected {want} - "
                "refusing")
    col = j2["collisions"]
    if col["c1_adjudicable"] or col["c2_tagged_n"] != 0 \
            or col["all_n"] != 65 or col["collision_free_n"] != 65:
        raise J3ReconciliationError(
            "published J2 collision facts differ from the tracked "
            "surface - refusing")


# ---------------------------------------------------------------------------
# Readout assembly (nodes -> edges -> qualifiers; no statistic computed)
# ---------------------------------------------------------------------------


def _panel_for(role: str, surfaces: Mapping[str, Any]) -> dict[str, Any]:
    return surfaces["j1b"]["panels"][role]


def _route_b_satisfied(node: Mapping[str, Any],
                       panel: Mapping[str, Any]) -> bool:
    """Route B: two design-distinct M3 measurements agree on the same
    non-response (B/C) state (J0 section 7). Computed from published
    states only; the contextual layer can never participate."""
    members = [m for m in node["route_b_members"]
               if m in panel["states"]]
    if len(members) < 2:
        return False
    primary = node["primary"]
    p_state = panel["states"].get(primary)
    if p_state not in _STATES_BC:
        return False
    return any(panel["states"][m] == p_state for m in members
               if m != primary)


def assemble_readout(surfaces: Mapping[str, Any], *,
                     reconcile: bool = True) -> dict[str, Any]:
    """The complete frozen readout: node readings, edge states,
    qualifiers, denominators, contextual display. Pure consumption of
    published evidence; nothing is recomputed."""
    if reconcile:
        reconcile_published_evidence(surfaces)
    j1b, j2 = surfaces["j1b"], surfaces["j2"]

    nodes: list[dict[str, Any]] = []
    readings: dict[str, dict[str, Any]] = {}
    for node in GRAPH_NODES:
        if node["node"] == "N0":
            entry = {
                "node": "N0", "role": node["role"], "panel": [],
                "primary": None, "m_class": None, "modifier": None,
                "states": {}, "reading": "ACTIVATED",
                "rule_path": ("activation definitional: all 65 "
                              "frame-complete decisions occurred "
                              "(J0 section 12.1); event occurrence only, "
                              "no market claim"),
                "note": node["note"]}
        else:
            panel = _panel_for(node["role"], surfaces)
            reading = role_reading(
                primary_state=panel["states"][node["primary"]],
                primary_m_class=node["m_class"],
                primary_usable=True,
                modifier=panel["modifier"])
            entry = {
                "node": node["node"], "role": node["role"],
                "panel": list(panel["members"]),
                "primary": node["primary"], "m_class": node["m_class"],
                "modifier": panel["modifier"],
                "states": dict(panel["states"]),
                "reading": reading["reading"],
                "rule_path": reading["rule_path"],
                "note": node["note"]}
        readings[node["role"]] = entry
        nodes.append(entry)

    edges: list[dict[str, Any]] = []
    for spec in GRAPH_EDGES:
        up = readings[spec["upstream"]]
        down_role = spec["downstream"]
        down_entry = readings[down_role]
        node_def = next(n for n in GRAPH_NODES
                        if n["role"] == down_role)
        panel = _panel_for(down_role, surfaces)
        downstream = {
            "primary_state": panel["states"][node_def["primary"]],
            "primary_m_class": node_def["m_class"],
            "primary_usable": True,
            "modifier": panel["modifier"],
            "route_b_satisfied": _route_b_satisfied(node_def, panel),
        }
        if spec["upstream_kind"] == "definitional":
            upstream_reading = "ACTIVATED"
            upstream_path = ("upstream activation definitional (all 65 "
                             "anchors exist); UPSTREAM NOT ACTIVATED and "
                             "DOWNSTREAM WITHOUT UPSTREAM structurally "
                             "unreachable on E1 (J0 section 12.3)")
        else:
            upstream_reading = up["reading"]
            upstream_path = up["rule_path"]
        adjudicated = edge_state(upstream_reading, downstream)
        edges.append({
            "edge": spec["edge"],
            "from": spec["upstream"], "to": down_role,
            "upstream_reading": upstream_reading,
            "upstream_path": upstream_path,
            "downstream_state": downstream["primary_state"],
            "downstream_m_class": downstream["primary_m_class"],
            "downstream_modifier": downstream["modifier"],
            "route_b_satisfied": downstream["route_b_satisfied"],
            "state": adjudicated["state"],
            "rule_path": adjudicated["rule_path"],
            "downstream_reading_display": down_entry["reading"],
        })

    tc = j2["timing_cells"]
    timing_qualifier = (
        f"{TIMING_QUALIFIER_SENTENCE} — published J2 [-5, -1] pre-event "
        f"states: raw_return {tc[13]['state']}; spy_relative_ar "
        f"{tc[14]['state']}; sector_relative_ar {tc[15]['state']}; sar "
        f"{tc[16]['state']}. The J0 section-15 withdrawal condition for "
        "the 1d concentration claim was not triggered (tracked J2 "
        "section 7). Timing qualifies temporal interpretation only; it "
        "rewrites no J1B node state and no edge state.")
    col = j2["collisions"]
    collision_qualifier = (
        f"exact [t, t+1] collision register: C2 `{col['c2_register']}` "
        f"({col['c2_register_dates']} calendar dates) tags "
        f"{col['c2_tagged_n']} of {col['all_n']} events; the C1 BLS CPI "
        "/ Employment Situation branch is unadjudicable in the published "
        "execution (no source-pinned era register); FOMC self-collision "
        f"invariant holds (minimum anchor spacing "
        f"{col['fomc_self_min_spacing']}). The collision-free "
        f"sensitivity over the adjudicable registers is the full frame "
        f"(N = {col['collision_free_n']}) and reproduces the published "
        "J1B surface vacuously. Events are described as outside "
        "known-register collisions only; no stronger clean-window claim "
        "exists. Collision status qualifies the readout and neither "
        "creates nor removes an edge state.")

    denominators = {
        "j1b_rolling_beta": {
            "available": j1b["cells"][1]["available"],
            "attempted": j1b["cells"][1]["attempted"],
            "reference_n": j1b["cells"][1]["reference_n"]},
        "j1b_raw_return": {
            "available": j1b["cells"][6]["available"],
            "attempted": j1b["cells"][6]["attempted"],
            "reference_n": j1b["cells"][6]["reference_n"]},
        "j1b_raw_change": {
            "available": j1b["cells"][10]["available"],
            "attempted": j1b["cells"][10]["attempted"],
            "reference_n": j1b["cells"][10]["reference_n"]},
        "j2_timing": {
            "available": tc[13]["available"],
            "attempted": tc[13]["attempted"],
            "reference_n": tc[13]["reference_n"]},
    }

    contextual = {
        "measurement": CONTEXTUAL_MEASUREMENT,
        "published_state": j1b["contextual_state"],
        "note": ("curve-shape contextual layer (J0 section 12.2): "
                 "displayed beside the graph as context only - not a "
                 "node, not a rates-panel member, no modifier input, no "
                 "Route B support, never a substitute for short-rate "
                 "repricing; it neither rescues nor contradicts N1"),
    }

    return {"contract": J3_CONTRACT, "nodes": nodes, "edges": edges,
            "timing_qualifier": timing_qualifier,
            "collision_qualifier": collision_qualifier,
            "denominators": denominators, "contextual": contextual,
            "surfaces": {"j1b": j1b, "j2": j2}}


# ---------------------------------------------------------------------------
# Deterministic report renderer (frozen vocabulary; no ranking)
# ---------------------------------------------------------------------------


def render_j3_report(readout: Mapping[str, Any], *,
                     provenance: Mapping[str, str]) -> str:
    j1b = readout["surfaces"]["j1b"]
    j2 = readout["surfaces"]["j2"]
    L: list[str] = []
    L.append("# J3 mechanism and transmission readout - the frozen graph "
             "adjudication (Mission J)")
    L.append("")
    L.append(f"Contract: `{J3_CONTRACT}` under the locked j0-v1 "
             "constitution (sections 5, 6, 7, 12, 13). J3 is a readout "
             "layer over the published J1B and J2 surfaces; it computes "
             "no new statistic of any kind. Where an edge conclusion "
             "would require a new statistic, the edge is MEASUREMENT "
             "UNRESOLVED by construction.")
    L.append("")
    L.append("## 1. Contract and provenance")
    L.append("")
    L.append(f"- execution commit: `{provenance['head']}`")
    L.append(f"- executed at: {provenance['timestamp']}")
    L.append("- source reports (tracked, published, consumed read-only): "
             "`stats/J1B_FOMC_ROBUSTNESS_RESULTS.md`; "
             "`stats/J2_TIMING_COLLISION_RESULTS.md`")
    L.append("- no-new-statistics statement: J3 computed no response "
             "value, no median-of-percentiles estimand, no placement "
             "calibration, no event subset, no return, no beta, and no "
             "test quantity; every number below is quoted from a tracked "
             "published surface.")
    L.append("- graph manifest (frozen, J0 section 12): `fomc_decision "
             "-> policy_rates_repricing -> "
             "balance_sheet_sensitive_second_order -> "
             "broad_financial_sector`; panels N1 = 2Y_CMT (M2 primary) + "
             "SHY (M3); N2 = KRE (M3 primary) + IAT + KBE; N3 = XLF (M3 "
             "primary) + VFH; 2S10S_CMT is the contextual curve-shape "
             "layer (not a node); SPY is context/benchmark only.")
    L.append("- edge-state enumeration (frozen, exactly five): "
             + "; ".join(EDGE_STATES) + ". No sixth state, no score, no "
             "probability, no edge ordering by strength.")
    L.append("")
    L.append("## 2. Published evidence inputs (quoted verbatim, frozen "
             "order preserved)")
    L.append("")
    L.append("### J1B 12-cell surface (window [t, t+1])")
    L.append("")
    L.append("| # | measurement | lens | events avail/att | ref N | MEMP "
             "| calib pct | state | LOYO | LOEO |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for no in sorted(j1b["cells"]):
        c = j1b["cells"][no]
        ov = j1b["overlays"].get(no, {"loyo": "-", "loeo": "-"})
        L.append(f"| {no} | {c['measurement']} | {c['lens']} | "
                 f"{c['available']} / {c['attempted']} | "
                 f"{c['reference_n']} | {c['memp']} | {c['calib']} | "
                 f"{c['state']} | {ov['loyo']} | {ov['loeo']} |")
    L.append("")
    L.append("### J2 state-bearing timing surface (window [-5, -1])")
    L.append("")
    L.append("| # | metric | events avail/att | ref N | MEMP | calib pct "
             "| state | LOYO | LOEO |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for no in sorted(j2["timing_cells"]):
        c = j2["timing_cells"][no]
        ov = j2["overlays"].get(no, {"loyo": "-", "loeo": "-"})
        L.append(f"| {no} | {c['metric']} | {c['available']} / "
                 f"{c['attempted']} | {c['reference_n']} | {c['memp']} | "
                 f"{c['calib']} | {c['state']} | {ov['loyo']} | "
                 f"{ov['loeo']} |")
    L.append("")
    L.append("MEMPs from different windows, references, or availability "
             "sets are not value-comparable and are never merged; the "
             "cells appear in frozen order.")
    L.append("")
    L.append("### Collision facts and denominators")
    L.append("")
    L.append(f"- {readout['collision_qualifier']}")
    d = readout["denominators"]
    L.append(f"- denominators: rolling-beta cells "
             f"{d['j1b_rolling_beta']['available']} / "
             f"{d['j1b_rolling_beta']['attempted']} events, reference "
             f"{d['j1b_rolling_beta']['reference_n']}; raw-return cells "
             f"{d['j1b_raw_return']['available']} / "
             f"{d['j1b_raw_return']['attempted']}, reference "
             f"{d['j1b_raw_return']['reference_n']}; Treasury raw-change "
             f"cells {d['j1b_raw_change']['available']} / "
             f"{d['j1b_raw_change']['attempted']}, reference "
             f"{d['j1b_raw_change']['reference_n']}; J2 timing cells "
             f"{d['j2_timing']['available']} / "
             f"{d['j2_timing']['attempted']}, reference "
             f"{d['j2_timing']['reference_n']}.")
    L.append("")
    L.append("## 3. Node readout")
    for n in readout["nodes"]:
        L.append("")
        L.append(f"### {n['node']} `{n['role']}`")
        L.append("")
        if n["node"] == "N0":
            L.append("- event trigger; not measured; activation "
                     "definitional (the decision occurred).")
        else:
            members = ", ".join(
                f"{m} ({'primary, ' if m == n['primary'] else ''}"
                f"{n['m_class'] if m == n['primary'] else 'M3'}): "
                f"{n['states'][m]}" for m in n["panel"])
            L.append(f"- panel: {members}")
            L.append(f"- measurement class of primary: {n['m_class']}")
            L.append(f"- role modifier (published): **{n['modifier']}**")
        L.append(f"- node reading: **{n['reading']}**")
        L.append(f"- rule path: {n['rule_path']}")
        L.append(f"- limitation: {n['note']}")
    L.append("")
    L.append("## 4. Edge readout (ordered precedence, J0 section 5)")
    for e in readout["edges"]:
        L.append("")
        L.append(f"### {e['edge']} `{e['from']}` -> `{e['to']}`")
        L.append("")
        L.append(f"- upstream reading: {e['upstream_reading']} "
                 f"({e['upstream_path']})")
        L.append(f"- downstream primary state: {e['downstream_state']} "
                 f"({e['downstream_m_class']}); role modifier "
                 f"{e['downstream_modifier']}; Route B satisfied: "
                 f"{e['route_b_satisfied']}")
        L.append(f"- final edge state: **{e['state']}**")
        L.append(f"- exact precedence path: {e['rule_path']}")
    L.append("")
    L.append("## 5. Timing qualification (carried, never rewriting "
             "states)")
    L.append("")
    L.append(f"- {readout['timing_qualifier']}")
    ov13 = j2["overlays"].get(13)
    if ov13:
        L.append(f"- published fragility carried: the J2 raw_return "
                 f"pre-event cell is knife-edge (LOYO {ov13['loyo']}, "
                 f"LOEO {ov13['loeo']}); the J1B post-anchor surface "
                 "carried 0 overlay flips.")
    L.append("- daily close-to-close data cannot resolve intraday "
             "repricing; the 2 p.m. ET statement release sits before the "
             "anchor-session close, so part of the same-session reaction "
             "is outside every daily window.")
    L.append("")
    L.append("## 6. Collision qualification (carried, never rewriting "
             "states)")
    L.append("")
    L.append(f"- {readout['collision_qualifier']}")
    L.append("")
    L.append("## 7. What the graph readout supports")
    L.append("")
    states = {e["edge"]: e["state"] for e in readout["edges"]}
    if all(s == "PROPAGATED" for s in states.values()):
        L.append("- Every frozen edge reads **PROPAGATED under the "
                 "frozen measurement rules**: the frozen upstream and "
                 "downstream roles show aligned elevated-response states "
                 "on the published [t, t+1] surface (E1, E2, E3).")
        L.append("- Every measured role carries **BROAD MEASUREMENT "
                 "CONSISTENCY**: no reading rests on a single proxy.")
        L.append("- Claim-ladder ceiling (J0 section 14, tier 5): a "
                 "**mechanism-consistent descriptive pattern** - the "
                 "predeclared linked roles satisfy the frozen state "
                 "rules with sufficient measurement adjudicability and "
                 "no proxy substitution. This is a descriptive "
                 "alignment, not proof of transmission, and it is never "
                 "phrased as a confirmed mechanism.")
        L.append("- The rates-role reading and therefore E1 and E2 are "
                 "**measurement-limited** (J0 section 8): the ideal M1 "
                 "repricing measure is unavailable, and the 2Y CMT "
                 "blends policy expectations with term premium; this "
                 "limitation travels with every affected statement.")
        L.append("- All of it is same-sample Class B evidence: "
                 "post-outcome robustness under prospectively frozen "
                 "new tests, never independent historical confirmation.")
    else:  # pragma: no cover - published surface adjudicates PROPAGATED
        for e in readout["edges"]:
            L.append(f"- {e['edge']}: {e['state']} - {e['rule_path']}")
    L.append("")
    L.append("## 8. Where transmission remains unresolved")
    L.append("")
    L.append("- The ideal M1 policy-repricing measure (fed funds futures "
             "/ OIS) is unavailable in the frozen substrate; the "
             "rates-role reading rests on an M2 official series plus an "
             "M3 investable proxy and stays measurement-limited.")
    L.append(f"- Temporal placement is unresolved at daily resolution: "
             f"{TIMING_QUALIFIER_SENTENCE} (section 5); the graph "
             "adjudicates response-magnitude alignment, not sequencing.")
    L.append("- The C1 BLS CPI / Employment Situation collision branch "
             "is unadjudicable in the published execution; freedom from "
             "those releases is not certified for any event window.")
    L.append("- The three panels and two windows are correlated "
             "same-sample views over overlapping events, assets, and "
             "reference structures - not independent replications.")
    L.append("- No panel produced MEASUREMENT DISAGREEMENT on the "
             "published surface; had one occurred, the affected role "
             "would carry no single reading and its edges would be "
             "MEASUREMENT UNRESOLVED.")
    L.append("")
    L.append("## 9. What J3 does not establish")
    L.append("")
    for item in (
            "causality (edge states are descriptive alignments under "
            "frozen measurement rules, never proof of transmission)",
            "prediction",
            "tradeability",
            "alpha",
            "independent historical confirmation of Mission I, J1B, or "
            "J2",
            "permanent price impact",
            "intraday sequencing (daily data cannot resolve it)",
            "a structural macro model",
            "mechanism proof beyond the frozen descriptive graph "
            "adjudication (tier-5 ceiling, J0 section 14)"):
        L.append(f"- {item};")
    L.append("- any hypothesis-test conclusion (calibration percentiles "
             "are placement positions, not test outcomes).")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI (gate -> execute -> verify)
# ---------------------------------------------------------------------------


def _emit(text: str) -> None:  # pragma: no cover - console seam
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--head", default="UNSET")
    ap.add_argument("--timestamp", default="UNSET")
    ap.add_argument("--out", default=str(REPORT_PATH))
    args = ap.parse_args(argv)
    if args.gate or args.execute or args.verify:
        surfaces = load_published_surfaces()
        reconcile_published_evidence(surfaces)
        checks = {
            "j1b_cells": len(surfaces["j1b"]["cells"]),
            "j2_cells": len(surfaces["j2"]["timing_cells"]),
            "panels": len(surfaces["j1b"]["panels"]),
            "edge_states": len(EDGE_STATES),
            "graph_nodes": len(GRAPH_NODES),
            "graph_edges": len(GRAPH_EDGES),
        }
        if args.gate:
            _emit("J3 gate reconciliation OK: "
                  + "; ".join(f"{k}={v}" for k, v in checks.items())
                  + "\n")
            return 0
        _emit(PRERUN_GATE_BANNER + "\n")
        readout = assemble_readout(surfaces)
        text = render_j3_report(
            readout, provenance={"head": args.head,
                                 "timestamp": args.timestamp})
        out = Path(args.out)
        if args.verify:
            same = out.read_text(encoding="utf-8") == text
            _emit(f"deterministic rerun byte-identical: {same}\n")
            return 0 if same else 1
        out.write_text(text, encoding="utf-8", newline="\n")
        _emit(f"wrote {out}\n")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Mission J research contract - tracked-artifact-backed evidence record.

Builds the structured, read-only representation of the completed and
published Mission J record (``mission-j-evidence-v1``) for application
consumers.

Sources of truth: the tracked final publications
``stats/J1B_FOMC_ROBUSTNESS_RESULTS.md``,
``stats/J2_TIMING_COLLISION_RESULTS.md``, and
``stats/J3_MECHANISM_TRANSMISSION_READOUT.md``, parsed at request time.
Every computed research number in the response is EXTRACTED from those
artifacts; none is written into this module (drift-tested).

This endpoint PUBLISHES closed results. It computes no return, no
median-of-percentiles estimand, no placement position, no subset, and it
never re-derives node or edge adjudication: the final published J3 node
readings, edge states, and explanation paths are parsed from the J3
publication itself. Artifact drift (missing file, malformed cardinality,
changed cell or edge identity) raises rather than serving stale, partial,
or reinterpreted numbers.

Fresh-clone contract: this module reads only tracked repository files. It
imports no database module, opens no sqlite connection, performs no
network I/O, and never touches ``events.db``, price caches, or providers.
J1B, J2, and J3 are returned as SEPARATE sections; nothing pools them
with each other or with any other mission's ledger.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scripts.j3_mechanism_readout import (EDGE_STATES, NODE_READINGS,
                                          parse_j1b_report,
                                          parse_j2_report)

_ROOT = Path(__file__).resolve().parents[1]
_STATS = _ROOT / "stats"

CONTRACT_VERSION = "mission-j-evidence-v1"

J1B_PUBLICATION_PATH = _STATS / "J1B_FOMC_ROBUSTNESS_RESULTS.md"
J2_PUBLICATION_PATH = _STATS / "J2_TIMING_COLLISION_RESULTS.md"
J3_PUBLICATION_PATH = _STATS / "J3_MECHANISM_TRANSMISSION_READOUT.md"

# Frozen identity manifests (identities only - never research values).
_J1B_CELL_IDENTITY: tuple[tuple[int, str, str], ...] = (
    (1, "KRE", "rolling_beta_ar"), (2, "IAT", "rolling_beta_ar"),
    (3, "KBE", "rolling_beta_ar"), (4, "XLF", "rolling_beta_ar"),
    (5, "VFH", "rolling_beta_ar"), (6, "IAT", "raw_return"),
    (7, "KBE", "raw_return"), (8, "XLF", "raw_return"),
    (9, "VFH", "raw_return"), (10, "2Y_CMT", "raw_change"),
    (11, "2S10S_CMT", "raw_change"), (12, "SHY", "raw_return"),
)
_J2_CELL_IDENTITY: tuple[tuple[int, str], ...] = (
    (13, "raw_return"), (14, "spy_relative_ar"),
    (15, "sector_relative_ar"), (16, "sar"),
)
_DIAGNOSTIC_IDENTITY: tuple[tuple[str, str], ...] = (
    ("D1", "raw_return"), ("D2", "spy_relative_ar"),
    ("D3", "sector_relative_ar"), ("D4", "sar"),
)
_NODE_IDENTITY: tuple[tuple[str, str], ...] = (
    ("N0", "fomc_decision"),
    ("N1", "policy_rates_repricing"),
    ("N2", "balance_sheet_sensitive_second_order"),
    ("N3", "broad_financial_sector"),
)
_EDGE_IDENTITY: tuple[tuple[str, str, str], ...] = (
    ("E1", "fomc_decision", "policy_rates_repricing"),
    ("E2", "policy_rates_repricing",
     "balance_sheet_sensitive_second_order"),
    ("E3", "balance_sheet_sensitive_second_order",
     "broad_financial_sector"),
)

# Frozen wording carried only after its presence is verified in the
# tracked artifact that owns it (interpretation never outlives evidence).
INSUFFICIENT_SUBSET_WORDING = ("insufficient subset under the frozen "
                               "procedure")
DIAGNOSTIC_STATUS_WORDING = ("descriptive timing diagnostic only; no "
                             "ordinary-reference state is assigned under "
                             "the frozen procedure")
COLLISION_LIMITATION_WORDING = "outside known-register collisions"
MEASUREMENT_LIMITED_MARKER = "ideal M1 policy-repricing measure"
CORRELATED_VIEWS_MARKER = "correlated robustness views"
CONTEXTUAL_ISOLATION_MARKER = "outside the rates-repricing proxy panel"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"mission-j artifact unreadable: {path.name}: {exc}") from exc


def _drift(message: str) -> ValueError:
    return ValueError(f"mission-j artifact drift: {message}; refusing to "
                      "serve")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _drift(message)


def _search(pattern: str, text: str, artifact: str) -> re.Match:
    m = re.search(pattern, text, re.MULTILINE)
    if m is None:
        raise _drift(f"{artifact} no longer matches required pattern "
                     f"{pattern!r}")
    return m


# ---------------------------------------------------------------------------
# Supplementary parsers (fields the shared publication parsers omit)
# ---------------------------------------------------------------------------

_OVERLAY_FULL_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|[^|]+\|\s*(\d+/\d+)\s*\|\s*(\d+/\d+)\s*\|"
    r"\s*(\d+)\s*->\s*(\d+)\s*\|\s*([0-9.]+|n/a)\s*\|\s*(True|False)"
    r"\s*\|\s*$")


def _parse_full_overlays(text: str, expected_cells: tuple[int, ...],
                         artifact: str) -> dict[int, dict[str, Any]]:
    """LOYO / LOEO / F3 columns of a published stability-overlay table."""
    out: dict[int, dict[str, Any]] = {}
    for line in text.splitlines():
        m = _OVERLAY_FULL_ROW.match(line.strip())
        if not m:
            continue
        no = int(m.group(1))
        if no in expected_cells and no not in out:
            out[no] = {
                "loyo": m.group(2), "loeo": m.group(3),
                "f3_reference_n": int(m.group(4)),
                "f3_canonical_n": int(m.group(5)),
                "f3_memp": m.group(6),
                "f3_sign_flip": m.group(7) == "True",
            }
    _require(sorted(out) == sorted(expected_cells),
             f"{artifact} stability-overlay table incomplete "
             f"(found cells {sorted(out)})")
    return out


_CELL_BULLET = re.compile(r"^- \*\*Cell (\d+) - ")
_UNAVAILABLE_BULLET = re.compile(
    r"^  - unavailable event (\S+): (\S+)\s*$")


def _parse_unavailable_events(text: str) -> dict[int, list[list[str]]]:
    out: dict[int, list[list[str]]] = {}
    current: int | None = None
    for line in text.splitlines():
        m = _CELL_BULLET.match(line)
        if m:
            current = int(m.group(1))
            out.setdefault(current, [])
            continue
        m = _UNAVAILABLE_BULLET.match(line)
        if m and current is not None:
            out[current].append([m.group(1), m.group(2)])
    return out


def _collect_bullets(text: str, header: str, artifact: str) -> list[str]:
    """Bullets under a section header, joining wrapped continuation lines."""
    idx = text.find(header)
    _require(idx >= 0, f"{artifact} section {header!r} missing")
    bullets: list[str] = []
    for line in text[idx + len(header):].splitlines():
        if line.startswith("## "):
            break
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif line.startswith("  ") and bullets and line.strip():
            bullets[-1] += " " + line.strip()
    _require(bool(bullets), f"{artifact} section {header!r} carries no "
                            "bullets")
    return bullets


_DIAG_ROW = re.compile(
    r"^\|\s*(D[0-9])\s*\|\s*(\S+)\s*\|\s*\[([-0-9]+),\s*([-0-9]+)\]\s*\|"
    r"\s*(\d+)\s*/\s*(\d+)\s*\|\s*(-?[0-9.]+)\s*\|\s*([0-9.]+)\s*\|"
    r"\s*(\w+)\s*\|\s*$")


def _parse_diagnostics(j2_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in j2_text.splitlines():
        m = _DIAG_ROW.match(line.strip())
        if m:
            rows.append({
                "id": m.group(1),
                "metric": m.group(2),
                "window": f"[{m.group(3)}, {m.group(4)}]",
                "available_event_n": int(m.group(5)),
                "attempted_event_n": int(m.group(6)),
                "median_response": m.group(7),
                "median_abs_response": m.group(8),
                "direction": m.group(9),
                "descriptive_only": True,
                "status_wording": DIAGNOSTIC_STATUS_WORDING,
            })
    _require([(r["id"], r["metric"]) for r in rows]
             == list(_DIAGNOSTIC_IDENTITY),
             "J2 descriptive-diagnostic table does not carry exactly "
             "D1-D4 in frozen order")
    return rows


_TIMING_LINE = re.compile(r"^- cell (1[3-6]) \((\w+)\): (.*)$")


def _parse_timing_interpretation(j2_text: str) -> list[str]:
    lines = []
    for line in j2_text.splitlines():
        m = _TIMING_LINE.match(line)
        if m:
            lines.append(line[2:].strip())
    _require(len(lines) == len(_J2_CELL_IDENTITY),
             "J2 frozen per-cell timing-interpretation lines incomplete")
    return lines


def _parse_c1_branch(j2_text: str) -> dict[str, str]:
    m = _search(
        r"^- C1 families 2-3 - (BLS CPI and BLS Employment Situation): "
        r"\*\*unadjudicable in this execution\*\*\. (.+)$",
        j2_text, J2_PUBLICATION_PATH.name)
    return {"status": "unadjudicable", "families": m.group(1),
            "reason": m.group(2).strip()}


# ---------------------------------------------------------------------------
# J3 final-publication parser (published states only; nothing re-derived)
# ---------------------------------------------------------------------------

_NODE_HEADER = re.compile(r"^### (N\d) `(\w+)`\s*$")
_EDGE_HEADER = re.compile(r"^### (E\d) `(\w+)` -> `(\w+)`\s*$")
_PANEL_MEMBER = re.compile(r"(\S+) \((primary, )?(M\d)\): ([A-Z_]+)")


def _parse_j3_publication(text: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    kind: str | None = None
    for line in text.splitlines():
        m = _NODE_HEADER.match(line)
        if m:
            current = {"node": m.group(1), "role": m.group(2),
                       "panel": [], "m_class": None, "modifier": None,
                       "reading": None, "rule_path": None,
                       "limitation": None}
            nodes.append(current)
            kind = "node"
            continue
        m = _EDGE_HEADER.match(line)
        if m:
            current = {"edge": m.group(1), "from": m.group(2),
                       "to": m.group(3), "upstream_reading": None,
                       "upstream_path": None, "downstream_state": None,
                       "downstream_m_class": None,
                       "downstream_modifier": None,
                       "route_b_satisfied": None, "state": None,
                       "rule_path": None}
            edges.append(current)
            kind = "edge"
            continue
        if line.startswith("## "):
            current, kind = None, None
            continue
        if current is None or not line.startswith("- "):
            continue
        body = line[2:].strip()
        if kind == "node":
            if body.startswith("panel: "):
                for pm in _PANEL_MEMBER.finditer(body[len("panel: "):]):
                    current["panel"].append({
                        "member": pm.group(1),
                        "primary": pm.group(2) is not None,
                        "m_class": pm.group(3),
                        "state": pm.group(4)})
            elif body.startswith("measurement class of primary: "):
                current["m_class"] = body.rsplit(" ", 1)[-1]
            elif body.startswith("role modifier (published): "):
                current["modifier"] = body.split("**")[1]
            elif body.startswith("node reading: "):
                current["reading"] = body.split("**")[1]
            elif body.startswith("rule path: "):
                current["rule_path"] = body[len("rule path: "):]
            elif body.startswith("limitation: "):
                current["limitation"] = body[len("limitation: "):]
        else:
            if body.startswith("upstream reading: "):
                m2 = re.match(
                    r"upstream reading: (ACTIVATED|NOT ACTIVATED|"
                    r"UNRESOLVED) \((.*)\)$", body)
                if m2:
                    current["upstream_reading"] = m2.group(1)
                    current["upstream_path"] = m2.group(2)
            elif body.startswith("downstream primary state: "):
                m2 = re.match(
                    r"downstream primary state: ([A-Z_]+) \((M\d)\); "
                    r"role modifier ([A-Z -]+); Route B satisfied: "
                    r"(True|False)$", body)
                if m2:
                    current["downstream_state"] = m2.group(1)
                    current["downstream_m_class"] = m2.group(2)
                    current["downstream_modifier"] = m2.group(3)
                    current["route_b_satisfied"] = m2.group(4) == "True"
            elif body.startswith("final edge state: "):
                current["state"] = body.split("**")[1]
            elif body.startswith("exact precedence path: "):
                current["rule_path"] = body[len("exact precedence "
                                                "path: "):]

    artifact = J3_PUBLICATION_PATH.name
    _require([(n["node"], n["role"]) for n in nodes]
             == list(_NODE_IDENTITY),
             f"{artifact} node sections do not carry exactly N0-N3 in "
             "frozen order")
    _require([(e["edge"], e["from"], e["to"]) for e in edges]
             == list(_EDGE_IDENTITY),
             f"{artifact} edge sections do not carry exactly E1-E3 with "
             "the frozen endpoints")
    for n in nodes:
        _require(n["reading"] in NODE_READINGS,
                 f"{artifact} node {n['node']} reading "
                 f"{n['reading']!r} is not a frozen node reading")
        _require(bool(n["rule_path"]),
                 f"{artifact} node {n['node']} carries no rule path")
    for e in edges:
        _require(e["state"] in EDGE_STATES,
                 f"{artifact} edge {e['edge']} state {e['state']!r} is "
                 "not one of the five frozen edge states")
        for field in ("upstream_reading", "upstream_path",
                      "downstream_state", "rule_path"):
            _require(bool(e[field]),
                     f"{artifact} edge {e['edge']} missing {field}")

    timing = _collect_bullets(text, "## 5. Timing qualification",
                              artifact)[0]
    collision = _collect_bullets(text, "## 6. Collision qualification",
                                 artifact)[0]
    supports = _collect_bullets(text, "## 7. What the graph readout "
                                      "supports", artifact)
    unresolved = _collect_bullets(text, "## 8. Where transmission "
                                        "remains unresolved", artifact)
    non_claims = _collect_bullets(text, "## 9. What J3 does not "
                                        "establish", artifact)
    _require("lens-dependent under daily measurement" in timing,
             f"{artifact} timing qualifier lost the frozen wording")
    _require(COLLISION_LIMITATION_WORDING in collision,
             f"{artifact} collision qualifier lost the frozen wording")
    _require(any("mechanism-consistent descriptive pattern" in s
                 for s in supports),
             f"{artifact} lost the frozen claim-ceiling wording")
    return {"nodes": nodes, "edges": edges, "timing_qualifier": timing,
            "collision_qualifier": collision, "supports": supports,
            "unresolved": unresolved, "non_claims": non_claims}


# ---------------------------------------------------------------------------
# Contract builder
# ---------------------------------------------------------------------------


def _provenance_entry(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"artifact": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def _parse_execution_metadata(text: str, artifact: str) -> dict[str, str]:
    """The execution commit and timestamp RECORDED in the publication.

    Every Mission J publication records both lines (J2/J3 under their
    "Contract and provenance" heading, J1B as a header bullet), so the
    contract requires them: a copy without them, or with a malformed
    value, refuses to serve rather than inferring anything from the
    current checkout.
    """
    commit = re.search(r"^- execution commit: `([0-9a-f]{40})`\s*$",
                       text, re.MULTILINE)
    executed = re.search(
        r"^- executed at: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*$",
        text, re.MULTILINE)
    if commit is None or executed is None:
        raise ValueError(
            f"mission-j artifact drift: {artifact} no longer records its "
            "execution commit / executed-at provenance; refusing to serve")
    return {"execution_commit": commit.group(1),
            "executed_at": executed.group(1)}


def build_mission_j_evidence_summary(
        *,
        j1b_path: Path | str = J1B_PUBLICATION_PATH,
        j2_path: Path | str = J2_PUBLICATION_PATH,
        j3_path: Path | str = J3_PUBLICATION_PATH,
) -> dict[str, Any]:
    """The published Mission J record as a structured, read-only contract.

    Reads only the tracked publications given (defaults: the canonical
    ``stats/`` files). Raises ``ValueError`` on any artifact drift. The
    complete payload is validated before anything is returned; a drift in
    any section returns nothing rather than a partial payload.
    """
    j1b_path, j2_path, j3_path = (Path(j1b_path), Path(j2_path),
                                  Path(j3_path))
    j1b_text = _read(j1b_path)
    j2_text = _read(j2_path)
    j3_text = _read(j3_path)

    try:
        j1b = parse_j1b_report(j1b_text)
        j2 = parse_j2_report(j2_text)
    except ValueError:
        raise
    except Exception as exc:  # J3ParseError and friends -> drift
        raise _drift(str(exc)) from exc

    # ---- J1B -------------------------------------------------------------
    got_identity = [(no, j1b["cells"][no]["measurement"],
                     j1b["cells"][no]["lens"]) for no in sorted(j1b["cells"])]
    _require(got_identity == list(_J1B_CELL_IDENTITY),
             "J1B 12-cell identity manifest changed")
    j1b_overlays = _parse_full_overlays(
        j1b_text, tuple(no for no, _, _ in _J1B_CELL_IDENTITY),
        j1b_path.name)
    unavailable = _parse_unavailable_events(j1b_text)
    j1b_cells: list[dict[str, Any]] = []
    for no, _, _ in _J1B_CELL_IDENTITY:
        c = j1b["cells"][no]
        ov = j1b_overlays[no]
        j1b_cells.append({
            "cell": no,
            "measurement": c["measurement"],
            "lens": c["lens"],
            "role": c["role"],
            "m_class": c["m_class"],
            "evidence_class": c["evidence_class"],
            "attempted_event_n": int(c["attempted"]),
            "available_event_n": int(c["available"]),
            "unavailable_events": unavailable.get(no, []),
            "reference_n": int(c["reference_n"]),
            "memp": c["memp"],
            "calibration_percentile": c["calib"],
            "node_state": c["state"],
            "loyo": ov["loyo"],
            "loeo": ov["loeo"],
            "f3_reference_n": ov["f3_reference_n"],
            "f3_canonical_n": ov["f3_canonical_n"],
            "f3_memp": ov["f3_memp"],
            "f3_sign_flip": ov["f3_sign_flip"],
        })
    panels = [{"role": role,
               "members": list(p["members"]),
               "primary": p["primary"],
               "states": dict(p["states"]),
               "modifier": p["modifier"]}
              for role, p in j1b["panels"].items()]
    panels.sort(key=lambda p: p["role"])
    _require(MEASUREMENT_LIMITED_MARKER in j1b_text,
             "J1B measurement-limited wording is no longer present")
    _require(CORRELATED_VIEWS_MARKER in j1b_text,
             "J1B correlated-views disclosure is no longer present")
    _require(CONTEXTUAL_ISOLATION_MARKER in j1b_text,
             "J1B contextual-layer isolation wording is no longer "
             "present")
    j1b_section = {
        "window": "[t, t+1]",
        "cells": j1b_cells,
        "panels": panels,
        "contextual_2s10s": {
            "measurement": "2S10S_CMT",
            "state": j1b["contextual_state"],
            "isolation_note": (
                "curve-shape contextual layer: state-bearing and "
                "contextual; outside the rates-repricing proxy panel, "
                "outside role modifiers, outside edge adjudication; "
                "context only, never a substitute for short-rate "
                "repricing"),
        },
        "measurement_limited": {
            "statement": (
                "measurement-limited: the ideal M1 policy-repricing "
                "measure (fed funds futures / OIS) is unavailable in "
                "the frozen substrate; the rates-role reading rests on "
                "an M2 official series plus an M3 investable proxy, and "
                "the 2Y CMT blends policy expectations with term "
                "premium"),
        },
        "correlated_views_disclosure": (
            "the frozen cells are correlated robustness views over "
            "overlapping events, assets, benchmarks, and reference "
            "structures - not independent replications and not "
            "independent statistical tests"),
        "non_claims": _collect_bullets(
            j1b_text, "## What J1B does not establish", j1b_path.name),
    }

    # ---- J2 --------------------------------------------------------------
    got_j2 = [(no, j2["timing_cells"][no]["metric"])
              for no in sorted(j2["timing_cells"])]
    _require(got_j2 == list(_J2_CELL_IDENTITY),
             "J2 state-bearing cell identity manifest changed")
    j2_overlays = _parse_full_overlays(
        j2_text, tuple(no for no, _ in _J2_CELL_IDENTITY), j2_path.name)
    j2_cells: list[dict[str, Any]] = []
    for no, _ in _J2_CELL_IDENTITY:
        c = j2["timing_cells"][no]
        ov = j2_overlays[no]
        j2_cells.append({
            "cell": no,
            "metric": c["metric"],
            "window": c["window"],
            "attempted_event_n": int(c["attempted"]),
            "available_event_n": int(c["available"]),
            "reference_n": int(c["reference_n"]),
            "memp": c["memp"],
            "calibration_percentile": c["calib"],
            "node_state": c["state"],
            "loyo": ov["loyo"],
            "loeo": ov["loeo"],
            "f3_reference_n": ov["f3_reference_n"],
            "f3_canonical_n": ov["f3_canonical_n"],
            "f3_memp": ov["f3_memp"],
            "f3_sign_flip": ov["f3_sign_flip"],
        })
    _require(DIAGNOSTIC_STATUS_WORDING in j2_text,
             "J2 descriptive-only diagnostic wording is no longer "
             "present")
    _require(INSUFFICIENT_SUBSET_WORDING in j2_text,
             "J2 frozen infeasible-subset wording is no longer present")
    _require(COLLISION_LIMITATION_WORDING in j2_text,
             "J2 known-register collision limitation wording is no "
             "longer present")
    col = j2["collisions"]
    raw_overlay = j2_overlays[_J2_CELL_IDENTITY[0][0]]
    j2_section = {
        "window": "[-5, -1]",
        "state_bearing": j2_cells,
        "diagnostics": _parse_diagnostics(j2_text),
        "timing_interpretation": _parse_timing_interpretation(j2_text),
        "raw_cell_fragility": {
            "metric": _J2_CELL_IDENTITY[0][1],
            "loyo": raw_overlay["loyo"],
            "loeo": raw_overlay["loeo"],
            "note": ("the raw-return pre-event cell is knife-edge: the "
                     "direction of its median-percentile reading flips "
                     "under the published leave-one-out perturbations "
                     "while its assigned state is unchanged"),
        },
        "collisions": {
            "interval": "[t, t+1]",
            "primary_n": col["all_n"],
            "collision_free_n": col["collision_free_n"],
            "c2": {
                "register": col["c2_register"],
                "register_dates": col["c2_register_dates"],
                "tagged_n": col["c2_tagged_n"],
                "of": col["all_n"],
                "subset_n": col["c2_subset_n"],
                "subset_status": INSUFFICIENT_SUBSET_WORDING,
            },
            "c1": _parse_c1_branch(j2_text),
            "fomc_self": {
                "min_anchor_spacing": col["fomc_self_min_spacing"],
                "violations": col["fomc_self_violations"],
            },
            "limitation": (
                "events are described as outside known-register "
                "collisions only; no stronger clean-window claim "
                "exists, and the C1 branch above is unadjudicable in "
                "the published execution"),
        },
    }

    # ---- J3 --------------------------------------------------------------
    j3_section = _parse_j3_publication(j3_text)

    return {
        "contract_version": CONTRACT_VERSION,
        "provenance": {
            "sources": {
                "j1b": _provenance_entry(j1b_path),
                "j2": _provenance_entry(j2_path),
                "j3": _provenance_entry(j3_path),
            },
            # Execution provenance RECORDED in each publication, parsed
            # at request time (never hand-copied, never inferred from the
            # current checkout).
            "execution": {
                "j1b": _parse_execution_metadata(j1b_text, j1b_path.name),
                "j2": _parse_execution_metadata(j2_text, j2_path.name),
                "j3": _parse_execution_metadata(j3_text, j3_path.name),
            },
            # No Mission J publication records a reproduction command
            # block — stated as null, never fabricated.
            "reproduction": None,
            "publication_status": (
                "Mission J is published and closed: constitution (J0), "
                "frozen data substrate (J1A), asset/benchmark challenge "
                "(J1B), timing and exact-window collision challenge "
                "(J2), and frozen mechanism/transmission readout (J3)."),
            "no_recompute_statement": (
                "This endpoint exposes published results and computes "
                "no research statistic: no return, no "
                "median-of-percentiles estimand, no placement position, "
                "no subset, and no node or edge re-adjudication; the "
                "final published J3 states are parsed from the tracked "
                "J3 publication."),
        },
        "j1b": j1b_section,
        "j2": j2_section,
        "j3": j3_section,
    }

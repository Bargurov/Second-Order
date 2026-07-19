"""Universal Event Dossiers - the complete published historical research
universe, one read-only dossier per event (U0).

``event-dossier-index-v1`` / ``event-dossier-v1``: 97 events (65 FOMC +
32 OPEC), every one individually addressable, none selected, ranked, or
curated.  The assembler joins, at request time and from tracked files
only:

  * the Mission I v2 event-level surface (identity order, anchor
    sessions, per-event observations, denominators, falsifier overlays)
    via the tested ``mission_i_evidence`` builder;
  * the G1A / G1B identity-and-source ledgers (event dates, official
    source references, schedule status);
  * the Mission G and Mission J builders for aggregate research,
    robustness, timing, and transmission context;
  * the G6C publication for the six published per-event dossiers - an
    enrichment tier DISCOVERED from the publication, never a manual
    case list and never a product universe.

Honesty floors: every section carries an explicit status (never a bare
null), aggregate labels stay aggregate context (``context_scope:
"aggregate"``) and are never assigned to an individual event, event
dates and anchor sessions stay separate, missing or structurally
unavailable evidence stays visible with a reason code, and identity
disagreements between authoritative tracked sources classify the whole
dossier CONTRADICTORY rather than being silently repaired.  Publication
order is preserved; nothing sorts by response, percentile, aggregate
state, magnitude, or completeness.

Fresh-clone contract: reads only tracked repository files; imports no
database module, opens no sqlite connection, performs no network I/O.
The untracked local archive is never consulted.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from routes.mission_g_evidence import build_mission_g_evidence_summary
from routes.mission_i_evidence import build_mission_i_evidence_summary
from routes.mission_j_evidence import build_mission_j_evidence_summary

_ROOT = Path(__file__).resolve().parents[1]
_STATS = _ROOT / "stats"

INDEX_CONTRACT_VERSION = "event-dossier-index-v1"
DETAIL_CONTRACT_VERSION = "event-dossier-v1"

G1A_PATH = _STATS / "G1A_FOMC_FRAME_INVENTORY.md"
G1B_PATH = _STATS / "G1B_OPEC_DESIGNED_RESERVOIR.md"
G3_PATH = _STATS / "G3_MECHANICAL_ELIGIBILITY.md"
G6C_PATH = _STATS / "G6C_REPRESENTATIVE_CASES.md"

MAPPING_VERSION = "g3-transmission-map-v1"

_FOMC_N = 65
_OPEC_N = 32
_ROWS_PER_EVENT = {"FOMC": 8, "OPEC": 12}

_SECTION_ORDER = (
    "identity",
    "source_provenance",
    "eligibility_denominators",
    "mechanism_asset_basis",
    "reaction_observations",
    "reaction_enrichment",
    "ordinary_period_context",
    "aggregate_research_context",
    "robustness_timing_transmission",
    "falsifier_fragility",
    "missingness_limitations",
    "evidence_class_claim_ceiling",
    "non_claim",
)

_UNAVAILABLE_STATUSES = {
    "structurally_unavailable", "not_applicable", "not_exposed",
    "unresolved",
}

NON_CLAIM_STATEMENT = (
    "This dossier assembles published descriptive evidence for one dated "
    "event. Aggregate labels remain aggregate context and are not "
    "individual-event classifications. The record is not a causal "
    "estimate, significance test, independent replication, prediction, "
    "trade signal or proof of a mechanism.")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"event-dossier source drift: {message}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"event-dossier artifact unreadable: {path.name}: {exc}"
        ) from exc


def _artifact_ref(path: Path, note: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {"artifact": f"stats/{path.name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "note": note}


def _section(status: str, reason_code: str, summary: str,
             data: Any, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": status, "reason_code": reason_code,
            "summary": summary, "data": data,
            "source_references": sources}


# ---------------------------------------------------------------------------
# Ledger parsers (identities only - never research values)
# ---------------------------------------------------------------------------

_G1A_ROW = re.compile(
    r"^\| `(fomc-[a-z0-9-]+)` \| (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| "
    r"([^|]+) \| ([^|]+) \| \[[^\]]+\]\(([^)]+)\) \| `([^`]+)` \|")


def _parse_g1a_ledger(text: str) -> dict[str, dict[str, str]]:
    """The frame-complete FOMC identity ledger: slug -> identity row."""
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = _G1A_ROW.match(line)
        if m is None:
            continue
        slug = m.group(1)
        _require(slug not in rows, f"G1A duplicate candidate key {slug}")
        rows[slug] = {
            "event_date": m.group(2),
            "publication_timestamp": m.group(3).strip(),
            "schedule_status": m.group(4).strip(),
            "source_description": m.group(5).strip(),
            "official_source_reference": m.group(6).strip(),
            "anchor_quality": m.group(7).strip(),
        }
    _require(len(rows) == _FOMC_N,
             f"G1A ledger carries {len(rows)} rows, expected {_FOMC_N}")
    return rows


_G1B_ROW = re.compile(
    r"^\| (D\d{2}) \| (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| ([^|]+) \| "
    r"([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|")
_G1B_CANONICAL = re.compile(r"^C\d+ `(opec-[a-z0-9-]+)`$")


def _parse_g1b_ledger(text: str) -> dict[str, dict[str, str]]:
    """The OPEC reservoir ledger restricted to the 32 canonical
    reservoir-ready identities (mirrors and the held identity carry no
    plain ``Cnn `slug``` cell and are excluded by the ledger's own
    vocabulary, not by any judgment here)."""
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = _G1B_ROW.match(line)
        if m is None:
            continue
        canonical = _G1B_CANONICAL.match(m.group(6).strip())
        if canonical is None:
            continue
        slug = canonical.group(1)
        _require(slug not in rows, f"G1B duplicate canonical identity {slug}")
        rows[slug] = {
            "event_date": m.group(2),
            "ledger_key": m.group(1),
            "official_source_reference": m.group(3).strip(),
            "source_description": m.group(4).strip(),
            "action_type": m.group(5).strip(),
            "anchor_quality": m.group(7).strip(),
        }
    _require(len(rows) == _OPEC_N,
             f"G1B ledger resolves {len(rows)} canonical identities, "
             f"expected {_OPEC_N}")
    return rows


# ---------------------------------------------------------------------------
# G3 canonical mapping parser (the universal family mechanism source)
# ---------------------------------------------------------------------------

_G3_MAP_ROW = re.compile(
    r"^\| (FOMC|OPEC[^|]*) \| `(\w+)` \| `(\w+)` \| `(\w+)` \| ([^|]+) \|")


def _parse_g3_mapping(text: str) -> dict[str, dict[str, str]]:
    """The frozen family-level transmission mapping from the tracked G3
    publication - the CANONICAL source of the universal mechanism
    hypothesis, asset basis, claim ceilings, and mapping version.  G6C is
    never consulted for these fields."""
    version = re.search(r"Mapping version: `(g3-transmission-map-v\d+)`",
                        text)
    _require(version is not None
             and version.group(1) == MAPPING_VERSION,
             "G3 mapping version drifted")
    mapping: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = _G3_MAP_ROW.match(line)
        if m is None:
            continue
        family = "FOMC" if m.group(1).startswith("FOMC") else "OPEC"
        _require(family not in mapping, "G3 mapping table duplicates a "
                 "family row")
        mapping[family] = {
            "primary": m.group(2),
            "market": m.group(3),
            "sector": m.group(4),
            "interpretation": m.group(5).strip(),
        }
    _require(set(mapping) == {"FOMC", "OPEC"}, "G3 mapping table drifted")
    for family, ticker_key in (("FOMC", "FOMC"), ("OPEC", "OPEC")):
        ceiling = re.search(
            rf"^- {ticker_key} / `\w+`: (.+)$", text, re.MULTILINE)
        _require(ceiling is not None,
                 f"G3 {family} claim ceiling drifted")
        mapping[family]["claim_ceiling"] = ceiling.group(1).strip()
    return mapping


# ---------------------------------------------------------------------------
# G6C enrichment parser (published per-event dossiers)
# ---------------------------------------------------------------------------

_G6C_META = re.compile(
    r"- event date: (\d{4}-\d{2}-\d{2}) \| lane: ([^|]+) \| family: (\w+)")
_G6C_READOUT_ROW = re.compile(
    r"^\| ([A-Za-z -]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")


def _parse_g6c_dossiers(text: str) -> dict[str, dict[str, Any]]:
    """The six published per-event dossiers, keyed by slug and parsed at
    the publication's own ``### `slug``` boundaries."""
    dossiers: dict[str, dict[str, Any]] = {}
    chunks = re.split(r"^### `([a-z0-9-]+)`$", text, flags=re.MULTILINE)
    for i in range(1, len(chunks) - 1, 2):
        slug, body = chunks[i], chunks[i + 1]
        meta = _G6C_META.search(body)
        _require(meta is not None, f"G6C dossier {slug} lost its meta line")
        hypothesis = re.search(
            r"- frozen transmission hypothesis: (.+)", body)
        source = re.search(r"- source \(G1 ledger\): (.+)", body)
        description = re.search(r"- source-native description: (.+)", body)
        assets = re.search(
            r"- assets: primary (\w+), market benchmark (\w+), sector "
            r"benchmark (\w+)", body)
        role = re.search(
            r"#### Role in the research record\n\n(.+)", body)
        _require(all(x is not None for x in
                     (hypothesis, source, description, assets, role)),
                 f"G6C dossier {slug} lost a frozen field")
        readout_rows: list[dict[str, str]] = []
        for line in body.splitlines():
            rm = _G6C_READOUT_ROW.match(line.strip())
            if rm is None or rm.group(1).strip() == "metric":
                continue
            if set(rm.group(2).strip()) <= set("-: "):
                continue
            readout_rows.append({
                "metric": rm.group(1).strip(),
                "1d": rm.group(2).strip(),
                "5d": rm.group(3).strip(),
                "20d": rm.group(4).strip(),
            })
        _require(len(readout_rows) == 4,
                 f"G6C dossier {slug} readout table drifted "
                 f"({len(readout_rows)} rows)")
        dossiers[slug] = {
            "event_date": meta.group(1),
            "family": meta.group(3).upper(),
            "frozen_transmission_hypothesis": hypothesis.group(1).strip(),
            "source_ledger_reference": source.group(1).strip(),
            "source_description": description.group(1).strip(),
            "assets": (assets.group(1), assets.group(2), assets.group(3)),
            "readout_rows": readout_rows,
            "role_in_record": role.group(1).strip(),
        }
    _require(len(dossiers) == 6,
             f"G6C publication carries {len(dossiers)} dossiers, expected 6")
    return dossiers


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _collect_universe(
        mission_i: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """The ordered 97-event universe and per-event row groups, derived
    from the Mission I v2 event-level surface (publication order:
    families in frozen order, events ascending by anchor session).
    Cross-cell inconsistencies are recorded, never repaired."""
    order: list[str] = []
    per_event: dict[str, dict[str, Any]] = {}
    for cell in mission_i["event_level"]["cells"]:
        for row in cell["rows"]:
            slug = row["event"]
            rec = per_event.get(slug)
            if rec is None:
                rec = {"family": cell["family"],
                       "anchor_session": row["anchor_session"],
                       "rows": [], "contradictions": []}
                per_event[slug] = rec
                order.append(slug)
            else:
                if rec["family"] != cell["family"]:
                    rec["contradictions"].append(
                        "family disagrees across Mission I cells")
                if rec["anchor_session"] != row["anchor_session"]:
                    rec["contradictions"].append(
                        "anchor session disagrees across Mission I cells")
            rec["rows"].append({
                "cell_key": cell["cell_key"],
                "horizon": cell["horizon"],
                "metric": cell["metric"],
                "response": row["response"],
                "abs_mid_rank_pct": row["abs_mid_rank_pct"],
                "signed_pct": row["signed_pct"],
            })
    for slug, rec in per_event.items():
        expected = _ROWS_PER_EVENT.get(rec["family"])
        if expected is None or len(rec["rows"]) != expected:
            rec["contradictions"].append(
                "Mission I cell coverage incomplete for this event")
    return order, per_event


def _percentile_method_note(mission_i: dict[str, Any]) -> str:
    method = mission_i["event_level"]["method"]
    return (f"{method['ordering_statement']} abs_mid_rank_pct is the "
            "published mid-rank method percentile, not a strength, rank, "
            "or probability score.")


def _build_dossier(
        slug: str,
        rec: dict[str, Any],
        *,
        mission_i: dict[str, Any],
        mission_g: dict[str, Any],
        mission_j: dict[str, Any],
        ledgers: dict[str, dict[str, dict[str, str]]],
        ledger_refs: dict[str, dict[str, Any]],
        g3_mapping: dict[str, dict[str, str]],
        g3_ref: dict[str, Any],
        g6c: dict[str, dict[str, Any]],
        g6c_ref: dict[str, Any],
        mission_g_refs: list[dict[str, Any]],
        mission_j_refs: dict[str, dict[str, Any]],
        i2b_ref: dict[str, Any],
        i1_ref: dict[str, Any],
        i2c_falsifiers_ref: dict[str, Any],
) -> dict[str, Any]:
    family = rec["family"]
    lane = next(f for f in mission_i["universe"]["families"]
                if f["family"] == family)
    primary_cells = {c["cell_key"]: c for c in mission_i["primary_cells"]}
    ledger_row = ledgers.get(family, {}).get(slug)
    ledger_ref = ledger_refs[family]
    contradictions = list(rec["contradictions"])
    if ledger_row is None:
        contradictions.append(
            "identity present on the Mission I event surface but absent "
            "from the family identity ledger")

    sections: dict[str, dict[str, Any]] = {}

    # ---- 1. identity -----------------------------------------------------
    if contradictions:
        sections["identity"] = _section(
            "contradictory", "identity_ledger_row_missing",
            "Authoritative tracked sources disagree on this identity; "
            "nothing is repaired or chosen silently.",
            {"candidate_id": slug, "family": family,
             "anchor_session": rec["anchor_session"],
             "conflicts": contradictions},
            [ledger_ref, i2b_ref])
    else:
        sections["identity"] = _section(
            "available", "exact_slug_join",
            "Exact identity join between the family identity ledger and "
            "the Mission I event-level surface; event date and anchor "
            "session are kept separate.",
            {"candidate_id": slug, "family": family,
             "event_date": ledger_row["event_date"],
             "anchor_session": rec["anchor_session"],
             "identity_status": "exact_join"},
            [ledger_ref, i2b_ref])

    # ---- 2. source provenance -------------------------------------------
    if ledger_row is None:
        sections["source_provenance"] = _section(
            "unresolved", "identity_ledger_row_missing",
            "No tracked ledger row resolves this identity; no source is "
            "invented in its place.",
            None, [ledger_ref, i2b_ref])
    else:
        prov: dict[str, Any] = {
            "source_description": ledger_row["source_description"],
            "official_source_reference":
                ledger_row["official_source_reference"],
            "source_artifact": ledger_ref["artifact"],
            "source_row_key": slug,
            "artifact_sha256": ledger_ref["sha256"],
            "anchor_quality": ledger_row["anchor_quality"],
        }
        if family == "FOMC":
            prov["publication_timestamp"] = (
                ledger_row["publication_timestamp"])
            prov["schedule_status"] = ledger_row["schedule_status"]
        else:
            prov["ledger_key"] = ledger_row["ledger_key"]
            prov["action_type"] = ledger_row["action_type"]
        sections["source_provenance"] = _section(
            "available", "tracked_ledger_row",
            "Official dated source pinned in the tracked identity "
            "ledger; the untracked local archive is never consulted.",
            prov, [ledger_ref])

    # ---- 3. eligibility and denominators --------------------------------
    ref_by_horizon: dict[str, Any] = {}
    available_h: list[str] = []
    unavailable_h: list[str] = []
    for hz in lane["horizons"]:
        ref_by_horizon[hz["horizon"]] = {
            "reference_n_attempted": hz["reference_n_attempted"],
            "reference_n_available": hz["reference_n_available"],
            "non_overlapping_blocks": hz["non_overlapping_reference_n"],
            "status": hz["status"],
        }
        if hz["status"] == "feasible":
            available_h.append(hz["horizon"])
        else:
            unavailable_h.append(hz["horizon"])
    sections["eligibility_denominators"] = _section(
        "available", "mission_i_universe_lane",
        f"{family} family denominator and per-horizon ordinary reference "
        "denominators from the frozen Mission I universe funnel; the two "
        "family ledgers are never pooled.",
        {"family_event_n": lane["study_event_n_available"],
         "family_event_n_attempted": lane["study_event_n_attempted"],
         "reference_n_by_horizon": ref_by_horizon,
         "available_horizons": available_h,
         "unavailable_horizons": unavailable_h,
         "eligibility_gate": ("frozen I1 candidate-universe funnel "
                              "(era, estimation, forward, gap, and "
                              "exclusion cuts)")},
        [i1_ref, i2b_ref])

    # ---- 4. mechanism and asset basis -----------------------------------
    # Canonical source: the tracked G3 mapping contract (a pure function
    # of family). G6C is never consulted here - enrichment must not
    # define universal core fields.
    canonical = g3_mapping[family]
    sections["mechanism_asset_basis"] = _section(
        "available", "canonical_g3_family_mapping",
        "Frozen family-level transmission mapping from the tracked G3 "
        "mapping contract - family context, not a bespoke event-level "
        "causal finding.",
        {"mechanism_hypothesis": canonical["interpretation"],
         "mechanism_role": ("family-level frozen mapping context; not an "
                            "event-level causal finding"),
         "scope": "family_level",
         "primary_asset": canonical["primary"],
         "market_benchmark": canonical["market"],
         "sector_benchmark": canonical["sector"],
         "price_basis_policy": lane["price_basis_policy"].lstrip("- "),
         "claim_ceiling": canonical["claim_ceiling"],
         "mapping_version": {
             "status": "available",
             "value": MAPPING_VERSION,
             "source_artifact": g3_ref["artifact"]}},
        [g3_ref, i2b_ref])

    # ---- 5. reaction observations ---------------------------------------
    obs_rows = [{k: r[k] for k in ("horizon", "metric", "response",
                                   "abs_mid_rank_pct", "signed_pct")}
                for r in rec["rows"]]
    sections["reaction_observations"] = _section(
        "available", "mission_i_event_level_rows",
        "Every published per-event observation for this event from the "
        "Mission I event-level surface, in publication order.",
        {"rows": obs_rows,
         "method_note": _percentile_method_note(mission_i)},
        [i2b_ref])

    # ---- 6. reaction enrichment (G6C tier) -------------------------------
    g6c_row = g6c.get(slug)
    if g6c_row is not None:
        canonical_assets = (canonical["primary"], canonical["market"],
                            canonical["sector"])
        if g6c_row["assets"] != canonical_assets:
            # G6C may corroborate the canonical mapping but never
            # redefine it - a conflicting enrichment mapping is exposed
            # as a contradiction, not silently resolved either way.
            sections["reaction_enrichment"] = _section(
                "contradictory", "g6c_mapping_conflicts_canonical_map",
                "The G6C enrichment dossier states an asset mapping that "
                "conflicts with the canonical G3 family mapping; neither "
                "source is silently chosen.",
                {"canonical_mapping": list(canonical_assets),
                 "g6c_mapping": list(g6c_row["assets"])},
                [g6c_ref, g3_ref])
        else:
            sections["reaction_enrichment"] = _section(
                "available", "g6c_published_per_event_dossier",
                "Published G6C per-event dossier: four-lens 1d/5d/20d "
                "readout and role wording - illustration-only enrichment, "
                "never proof and never a universe.",
                {"readout_rows": g6c_row["readout_rows"],
                 "role_in_record": g6c_row["role_in_record"],
                 "source_description": g6c_row["source_description"],
                 "source_ledger_reference":
                     g6c_row["source_ledger_reference"]},
                [g6c_ref])
    else:
        sections["reaction_enrichment"] = _section(
            "not_exposed", "per_event_reaction_not_published",
            "No published per-event reaction dossier exists for this "
            "event; the six G6C dossiers are an enrichment tier, not a "
            "coverage requirement.",
            None, [g6c_ref])

    # ---- 7. ordinary-period context --------------------------------------
    ordinary_rows = []
    for r in rec["rows"]:
        pc = primary_cells[r["cell_key"]]
        ordinary_rows.append({
            "cell_key": r["cell_key"],
            "family": family,
            "horizon": r["horizon"],
            "metric": r["metric"],
            "event_n": pc["event_n_available"],
            "reference_n": pc["reference_n_available"],
            "published_memp": pc["memp"],
            "published_signed_percentile_median":
                pc["signed_percentile_median"],
            "event_response": r["response"],
            "abs_mid_rank_pct": r["abs_mid_rank_pct"],
            "signed_pct": r["signed_pct"],
        })
    ordinary_data: dict[str, Any] = {
        "rows": ordinary_rows,
        "method_note": _percentile_method_note(mission_i),
    }
    if family == "FOMC":
        fomc_20d = next(h for h in lane["horizons"]
                        if h["horizon"] == "20d")
        ordinary_data["fomc_20d"] = {
            "status": "structurally_unavailable",
            "reason_code": "fomc_20d_ordinary_substrate_unavailable",
            "limitation": fomc_20d["limitation"] or "",
        }
    sections["ordinary_period_context"] = _section(
        "available", "mission_i_cells_joined",
        "This event's published observations joined to their frozen "
        "ordinary-period cells with both denominators and the published "
        "aggregates visible.",
        ordinary_data, [i2b_ref])

    # ---- 8. aggregate research context -----------------------------------
    contexts: list[dict[str, Any]] = [{
        "context_scope": "aggregate",
        "source": "mission_i",
        "evidence_class": ("Mission I descriptive / comparative "
                           "ordinary-period evidence"),
        "family_readouts": [
            {"horizon": r["horizon"], "headline": r["headline"]}
            for r in mission_i["family_horizon_readout"]
            if r["family"] == family],
        "cell_states": [
            {"cell_key": c["cell_key"], "memp": c["memp"],
             "memp_direction": c["state"]["memp_direction"],
             "f6_position": c["state"]["f6_position"]}
            for c in mission_i["primary_cells"]
            if c["family"] == family],
    }]
    if family == "FOMC":
        contexts.append({
            "context_scope": "aggregate",
            "source": "mission_g",
            "evidence_class": "Mission G descriptive historical evidence",
            "statement": mission_g["main_result"]["fomc_null"]["statement"],
            "stability": mission_g["stability"],
        })
    else:
        contexts.append({
            "context_scope": "aggregate",
            "source": "mission_g",
            "evidence_class": "Mission G descriptive historical evidence",
            "statement": mission_g["bounded_opec_association"]["wording"],
            "confound_note":
                mission_g["bounded_opec_association"]["confound_note"],
            "stability": mission_g["stability"],
        })
    sections["aggregate_research_context"] = _section(
        "available", "aggregate_context_only",
        "Published aggregate conclusions for this event's family - "
        "context for reading the event, never an individual-event label.",
        {"contexts": contexts,
         "non_inheritance_note": (
             "aggregate labels and conclusions describe published "
             "family-level surfaces; no aggregate state is inherited by "
             "this event as an individual verdict")},
        [i2b_ref] + mission_g_refs)

    # ---- 9. robustness / timing / transmission ---------------------------
    if family == "FOMC":
        j1b = mission_j["j1b"]
        j2 = mission_j["j2"]
        j3 = mission_j["j3"]
        mission_j_block: dict[str, Any] = {
            "status": "available",
            "context_scope": "aggregate",
            "evidence_class": ("Mission J same-sample Class B robustness "
                               "(prospectively frozen post-outcome "
                               "challenges)"),
            "j1b_cells": [
                {"cell": c["cell"], "measurement": c["measurement"],
                 "lens": c["lens"], "role": c["role"],
                 "events": (f"{c['available_event_n']} / "
                            f"{c['attempted_event_n']}"),
                 "unavailable_events": c["unavailable_events"],
                 "label": c["node_state"]}
                for c in j1b["cells"]],
            "j1b_panels": [
                {"role": p["role"], "modifier": p["modifier"]}
                for p in j1b["panels"]],
            "measurement_limited":
                j1b["measurement_limited"]["statement"],
            "correlated_views_disclosure":
                j1b["correlated_views_disclosure"],
            "j2_timing_cells": [
                {"metric": c["metric"], "window": c["window"],
                 "label": c["node_state"]}
                for c in j2["state_bearing"]],
            "j2_raw_cell_fragility": j2["raw_cell_fragility"]["note"],
            "c2_opec_collision_tags": (
                f"{j2['collisions']['c2']['tagged_n']}/"
                f"{j2['collisions']['c2']['of']}"),
            "c1_status": j2["collisions"]["c1"]["status"],
            "c1_note": j2["collisions"]["limitation"],
            "j3_edges": j3["edges"],
            "j3_note": ("PROPAGATED is a frozen descriptive edge label "
                        "at the published claim ceiling, not event-level "
                        "causal transmission"),
        }
    else:
        mission_j_block = {
            "status": "not_applicable",
            "reason_code": "mission_j_fomc_only",
            "context_scope": "aggregate",
            "note": ("Mission J challenges the inherited FOMC one-day "
                     "reading over the 65-event FOMC frame only; no "
                     "OPEC robustness surface exists in Mission J"),
        }
    mission_g_block: dict[str, Any] = {
        "status": "available",
        "context_scope": "aggregate",
        "evidence_class": "Mission G descriptive historical evidence",
        "stability": mission_g["stability"],
    }
    if family == "OPEC":
        mission_g_block["bounded_association"] = (
            mission_g["bounded_opec_association"]["wording"])
        mission_g_block["credit_limitation"] = (
            mission_g["credit_limitation"])
    else:
        mission_g_block["fomc_null"] = (
            mission_g["main_result"]["fomc_null"]["statement"])
    robustness_refs = list(mission_g_refs)
    if family == "FOMC":
        robustness_refs += [mission_j_refs["j1b"], mission_j_refs["j2"],
                            mission_j_refs["j3"]]
    sections["robustness_timing_transmission"] = _section(
        "available", "aggregate_context_only",
        "Published robustness, timing, and transmission surfaces for "
        "this event's family - aggregate context with its own evidence "
        "class, never an event verdict.",
        {"mission_g": mission_g_block, "mission_j": mission_j_block},
        robustness_refs)

    # ---- 10. falsifier and fragility -------------------------------------
    overlays = []
    for r in rec["rows"]:
        pc = primary_cells[r["cell_key"]]
        overlays.append({
            "cell_key": r["cell_key"],
            "f1_loyo": pc["f1_loyo"],
            "f2_loeo": pc["f2_loeo"],
            "f3_sign_flip": pc["f3_overlap_decimation"]["sign_flip"],
        })
    falsifier_data: dict[str, Any] = {
        "scope_note": ("family-level falsifier context; no per-event "
                       "falsifier outcome is assigned"),
        "battery_disclosure":
            mission_i["falsifiers"]["battery_disclosure"].replace("**", ""),
        "cell_overlays": overlays,
    }
    if family == "FOMC":
        knife = mission_i["fragility"]["knife_edge"]
        falsifier_data["knife_edge"] = {
            "scope": "family-level fragility context",
            "cell_key": knife["cell_key"],
            "memp": knife["memp"],
            "f1_loyo": knife["f1_loyo"],
            "f2_loeo": knife["f2_loeo"],
        }
    else:
        falsifier_data["era_bounded_credit"] = (
            mission_g["credit_limitation"])
        falsifier_data["calendar_time_confound"] = (
            mission_g["bounded_opec_association"]["confound_note"])
    falsifier_refs = [i2c_falsifiers_ref, i2b_ref]
    if family == "OPEC":
        falsifier_refs += mission_g_refs
    sections["falsifier_fragility"] = _section(
        "available", "published_falsifier_context",
        "Published falsifier and fragility context applicable to this "
        "event's family and cells.",
        falsifier_data, falsifier_refs)

    # ---- 11. missingness and limitations ---------------------------------
    items: list[dict[str, str]] = [
        {"reason_code": "computation_date_not_recorded",
         "statement": ("computation dates are recorded in no Mission I "
                       "publication and are stated null, never "
                       "inferred")},
        {"reason_code": "execution_commit_not_recorded",
         "statement": ("execution commits are recorded in no Mission I "
                       "publication and are stated null, never "
                       "inferred")},
        {"reason_code": "source_section_not_exposed",
         "statement": ("no source-section field is exposed by "
                       "mission-i-evidence-v2; the source artifact and "
                       "hash are exposed instead")},
        {"reason_code": "aggregate_context_only",
         "statement": ("robustness, timing, transmission, and falsifier "
                       "surfaces are aggregate-level published context; "
                       "no per-event adjudication exists")},
    ]
    if ledger_row is not None:
        items.append({
            "reason_code": "scheduled_anchor_limitation",
            "statement": (f"anchor quality {ledger_row['anchor_quality']}: "
                          "anticipation cannot be separated from the "
                          "decision at a scheduled announcement")})
    if family == "FOMC":
        items.extend([
            {"reason_code": "fomc_20d_ordinary_substrate_unavailable",
             "statement": ("the FOMC 20d ordinary-period comparison is "
                           "structurally unavailable - not a data gap")},
            {"reason_code": "ideal_rates_measure_unavailable",
             "statement": mission_j["j1b"]["measurement_limited"][
                 "statement"]},
            {"reason_code": "collision_register_unadjudicable",
             "statement": mission_j["j2"]["collisions"]["limitation"]},
            {"reason_code": "credit_source_pre_window",
             "statement": ("HY OAS coverage is era-bounded by the "
                           "surviving source window; pre-window FOMC "
                           "events carry no credit state")},
        ])
    else:
        items.extend([
            {"reason_code": "credit_source_pre_window",
             "statement": ("the OPEC credit lens is era-bounded and "
                           "secondary-only; pre-window events carry no "
                           "credit state")},
            {"reason_code": "mission_j_fomc_only",
             "statement": ("no Mission J robustness surface exists for "
                           "OPEC events")},
        ])
    missingness_refs = [i2b_ref, ledger_ref] + mission_g_refs
    if family == "FOMC":
        # the M1 and C1 limitation statements render from Mission J and
        # must cite it, never only an identity ledger
        missingness_refs += [mission_j_refs["j1b"], mission_j_refs["j2"]]
    sections["missingness_limitations"] = _section(
        "available", "missingness_inventory",
        "Everything known to be missing, structurally unavailable, "
        "unadjudicable, or aggregate-only for this event - research "
        "outputs, not implementation defects.",
        {"items": items}, missingness_refs)

    # ---- 12. evidence class and claim ceiling -----------------------------
    classes = [
        "Mission G descriptive historical evidence (outcome-blind "
        "frozen chain)",
        "Mission I descriptive / comparative ordinary-period evidence "
        "(frozen before any outcome comparison)",
    ]
    if family == "FOMC":
        classes.append(
            "Mission J same-sample Class B robustness (prospectively "
            "frozen post-outcome challenges)")
    if g6c_row is not None:
        classes.append(
            "G6C illustration-only enrichment (published per-event "
            "dossier)")
    class_refs = [i2b_ref] + mission_g_refs
    if family == "FOMC":
        class_refs.append(mission_j_refs["j1b"])
    if g6c_row is not None:
        class_refs.append(g6c_ref)
    sections["evidence_class_claim_ceiling"] = _section(
        "available", "published_evidence_classes",
        "The evidence classes that apply to this dossier, kept separate "
        "and never pooled - each named program cited.",
        {"classes": classes,
         "pooling_prohibition": mission_g["lanes"]["pooling_prohibition"],
         "claim_ceiling": ("descriptive published evidence only; the "
                           "strictest applicable published ceiling "
                           "governs every reading")},
        class_refs)

    # ---- 13. explicit non-claim -------------------------------------------
    sections["non_claim"] = _section(
        "available", "permanent_non_claim",
        "The permanent non-claim carried by every dossier.",
        {"statement": NON_CLAIM_STATEMENT},
        [{"artifact": DETAIL_CONTRACT_VERSION,
          "note": ("the dossier contract itself carries this permanent "
                   "non-claim")}])

    # ---- top-level status --------------------------------------------------
    statuses = [sections[name]["status"] for name in _SECTION_ORDER]
    if "contradictory" in statuses:
        top = "CONTRADICTORY"
    elif "unresolved" in statuses:
        top = "PARTIAL"
    else:
        top = "COMPLETE"

    ordered_sections = {name: sections[name] for name in _SECTION_ORDER}
    return {
        "contract_version": DETAIL_CONTRACT_VERSION,
        "candidate_id": slug,
        "top_level_status": top,
        "enrichment_tier": ("published_per_event_dossier"
                            if g6c_row is not None
                            else "core_published_evidence"),
        "sections": ordered_sections,
    }


def _normalize_ref(ref: dict[str, Any], note: str) -> dict[str, Any]:
    """One deterministic reference shape over the upstream builders'
    provenance entries (some record bare filenames)."""
    artifact = ref["artifact"]
    if not artifact.startswith("stats/"):
        artifact = f"stats/{artifact}"
    return {"artifact": artifact, "sha256": ref["sha256"],
            "bytes": ref["bytes"], "note": note}


def _resolve_inputs(
        mission_i_summary: dict[str, Any] | None,
        mission_g_summary: dict[str, Any] | None,
        mission_j_summary: dict[str, Any] | None,
        g1a_path: Path | str,
        g1b_path: Path | str,
        g6c_path: Path | str,
        g3_path: Path | str,
) -> dict[str, Any]:
    mission_i = (mission_i_summary if mission_i_summary is not None
                 else build_mission_i_evidence_summary())
    mission_g = (mission_g_summary if mission_g_summary is not None
                 else build_mission_g_evidence_summary())
    mission_j = (mission_j_summary if mission_j_summary is not None
                 else build_mission_j_evidence_summary())
    g1a_path, g1b_path, g6c_path, g3_path = (
        Path(g1a_path), Path(g1b_path), Path(g6c_path), Path(g3_path))
    g3_mapping = _parse_g3_mapping(_read(g3_path))
    # The canonical mapping and the Mission I family basis are two
    # authoritative tracked statements of the same assets; disagreement
    # is source drift and refuses service rather than choosing one.
    for lane in mission_i["universe"]["families"]:
        canonical = g3_mapping[lane["family"]]
        _require(
            (canonical["primary"], canonical["market"],
             canonical["sector"])
            == (lane["primary"], lane["market_benchmark"],
                lane["sector_benchmark"]),
            f"canonical G3 mapping disagrees with the Mission I "
            f"{lane['family']} family basis")
    g6c = _parse_g6c_dossiers(_read(g6c_path))
    discovered = {
        slot["candidate_id"]
        for slot in mission_g["representative_cases"]["cases"]}
    _require(discovered == set(g6c),
             "G6C dossier headings disagree with the published six-slot "
             "selection ledger")
    # The Mission G values this assembler renders (stability, the FOMC
    # null, the bounded OPEC association, the credit limitation, the
    # pooling prohibition) come from the non-G6C Mission G publications;
    # G6C is cited separately and exactly where enrichment data renders,
    # so it is excluded here rather than over-cited everywhere.
    g6c_artifact_name = f"stats/{Path(g6c_path).name}"
    mission_g_refs = [
        _normalize_ref(ref, f"Mission G evidence source ({key})")
        for key, ref in sorted(
            mission_g["provenance"]["sources"].items())]
    mission_g_refs = [ref for ref in mission_g_refs
                     if ref["artifact"] != g6c_artifact_name]
    _require(len(mission_g_refs) > 0,
             "Mission G provenance sources drifted to G6C-only")
    mission_j_refs = {
        key: _normalize_ref(
            mission_j["provenance"]["sources"][key],
            f"Mission J evidence source ({key})")
        for key in ("j1b", "j2", "j3")}
    return {
        "mission_i": mission_i,
        "mission_g": mission_g,
        "mission_j": mission_j,
        "ledgers": {"FOMC": _parse_g1a_ledger(_read(g1a_path)),
                    "OPEC": _parse_g1b_ledger(_read(g1b_path))},
        "ledger_refs": {
            "FOMC": _artifact_ref(
                g1a_path, "frame-complete FOMC identity and source "
                "ledger"),
            "OPEC": _artifact_ref(
                g1b_path, "OPEC designed-reservoir identity and source "
                "ledger (32 canonical reservoir-ready identities)"),
        },
        "g3_mapping": g3_mapping,
        "g3_ref": _artifact_ref(
            g3_path, f"canonical frozen family mapping "
            f"({MAPPING_VERSION})"),
        "g6c": g6c,
        "g6c_ref": _artifact_ref(
            g6c_path, "published per-event dossiers (enrichment tier "
            "only - never a universal core source)"),
        "mission_g_refs": mission_g_refs,
        "mission_j_refs": mission_j_refs,
        "i2b_ref": dict(
            mission_i["provenance"]["sources"]["i2b_memp"],
            note=("Mission I event-level surface via "
                  f"{mission_i['contract_version']}")),
        "i1_ref": dict(
            mission_i["provenance"]["sources"]["i1_universe"],
            note="Mission I candidate-universe funnel"),
        "i2c_falsifiers_ref": dict(
            mission_i["provenance"]["sources"]["i2c_falsifiers"],
            note="Mission I falsifier battery publication"),
    }


def _assemble(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    order, per_event = _collect_universe(inputs["mission_i"])
    return [
        _build_dossier(
            slug, per_event[slug],
            mission_i=inputs["mission_i"],
            mission_g=inputs["mission_g"],
            mission_j=inputs["mission_j"],
            ledgers=inputs["ledgers"],
            ledger_refs=inputs["ledger_refs"],
            g3_mapping=inputs["g3_mapping"],
            g3_ref=inputs["g3_ref"],
            g6c=inputs["g6c"],
            g6c_ref=inputs["g6c_ref"],
            mission_g_refs=inputs["mission_g_refs"],
            mission_j_refs=inputs["mission_j_refs"],
            i2b_ref=inputs["i2b_ref"],
            i1_ref=inputs["i1_ref"],
            i2c_falsifiers_ref=inputs["i2c_falsifiers_ref"],
        )
        for slug in order
    ]


def build_all_event_dossiers(
        *,
        mission_i_summary: dict[str, Any] | None = None,
        mission_g_summary: dict[str, Any] | None = None,
        mission_j_summary: dict[str, Any] | None = None,
        g1a_path: Path | str = G1A_PATH,
        g1b_path: Path | str = G1B_PATH,
        g6c_path: Path | str = G6C_PATH,
        g3_path: Path | str = G3_PATH,
) -> list[dict[str, Any]]:
    """Every event dossier in publication order (the complete universe)."""
    return _assemble(_resolve_inputs(
        mission_i_summary, mission_g_summary, mission_j_summary,
        g1a_path, g1b_path, g6c_path, g3_path))


def build_event_dossier_index(
        *,
        mission_i_summary: dict[str, Any] | None = None,
        mission_g_summary: dict[str, Any] | None = None,
        mission_j_summary: dict[str, Any] | None = None,
        g1a_path: Path | str = G1A_PATH,
        g1b_path: Path | str = G1B_PATH,
        g6c_path: Path | str = G6C_PATH,
        g3_path: Path | str = G3_PATH,
) -> dict[str, Any]:
    """The index over the complete universe, in publication order."""
    inputs = _resolve_inputs(
        mission_i_summary, mission_g_summary, mission_j_summary,
        g1a_path, g1b_path, g6c_path, g3_path)
    dossiers = _assemble(inputs)
    events = []
    family_counts: dict[str, int] = {}
    status_counts = {"COMPLETE": 0, "PARTIAL": 0, "UNAVAILABLE": 0,
                     "CONTRADICTORY": 0}
    section_availability: dict[str, dict[str, int]] = {
        name: {} for name in _SECTION_ORDER}
    enrichment_counts = {"published_per_event_dossier": 0,
                         "core_published_evidence": 0}
    contradiction_events = 0
    contradiction_sections = 0
    for d in dossiers:
        family = d["sections"]["identity"]["data"]["family"]
        family_counts[family] = family_counts.get(family, 0) + 1
        status_counts[d["top_level_status"]] += 1
        enrichment_counts[d["enrichment_tier"]] += 1
        available = 0
        unavailable = 0
        contradictory = 0
        for name in _SECTION_ORDER:
            status = d["sections"][name]["status"]
            tally = section_availability[name]
            tally[status] = tally.get(status, 0) + 1
            if status == "available":
                available += 1
            elif status == "contradictory":
                contradictory += 1
            elif status in _UNAVAILABLE_STATUSES:
                unavailable += 1
        if d["top_level_status"] == "CONTRADICTORY":
            contradiction_events += 1
        contradiction_sections += contradictory
        identity = d["sections"]["identity"]["data"]
        events.append({
            "candidate_id": d["candidate_id"],
            "family": family,
            "event_date": identity.get("event_date", ""),
            "anchor_session": identity["anchor_session"],
            "top_level_status": d["top_level_status"],
            "available_section_count": available,
            "unavailable_section_count": unavailable,
            "contradictory_section_count": contradictory,
            "enrichment_tier": d["enrichment_tier"],
        })
    # Every load-bearing source, deterministically ordered and
    # deduplicated by artifact (first occurrence wins).
    generated_from: list[dict[str, Any]] = []
    seen_artifacts: set[str] = set()
    for ref in ([inputs["i2b_ref"], inputs["i1_ref"],
                 inputs["i2c_falsifiers_ref"],
                 inputs["ledger_refs"]["FOMC"],
                 inputs["ledger_refs"]["OPEC"], inputs["g3_ref"]]
                + inputs["mission_g_refs"]
                + [inputs["mission_j_refs"]["j1b"],
                   inputs["mission_j_refs"]["j2"],
                   inputs["mission_j_refs"]["j3"],
                   inputs["g6c_ref"]]):
        if ref["artifact"] not in seen_artifacts:
            seen_artifacts.add(ref["artifact"])
            generated_from.append(ref)
    return {
        "contract_version": INDEX_CONTRACT_VERSION,
        "universe": "historical_research",
        "generated_from": generated_from,
        "coverage": {
            "total": len(dossiers),
            "family_counts": family_counts,
            "status_counts": status_counts,
            "section_availability_counts": section_availability,
            "enrichment_counts": enrichment_counts,
            "contradiction_counts": {
                "events": contradiction_events,
                "sections": contradiction_sections,
            },
        },
        "events": events,
    }


def build_event_dossier(candidate_id: str,
                        **seams: Any) -> dict[str, Any] | None:
    """One dossier by candidate id; ``None`` for an unknown identifier."""
    for dossier in build_all_event_dossiers(**seams):
        if dossier["candidate_id"] == candidate_id:
            return dossier
    return None

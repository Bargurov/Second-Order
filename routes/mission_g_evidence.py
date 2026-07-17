"""Mission G research contract - tracked-artifact-backed evidence summary.

Builds the structured, read-only representation of the completed Mission G
historical research record for application consumers (H2).

Source of truth: the tracked ``stats/G*.md`` research artifacts, parsed at
request time. Every computed research number in the response is EXTRACTED
from those artifacts by the parsers below; none is written into this
module (drift-tested). Interpretation wording is authored here, carries no
numbers, and the two research-approved phrases (the bounded OPEC wording
and the representative-case status) are verified present in the tracked
artifacts at build time - artifact drift raises rather than serving stale
or wrong numbers.

Fresh-clone contract: this module reads only tracked repository files. It
imports no database module, opens no sqlite connection, performs no
network I/O, and never touches ``events.db``, price caches, or providers.
The accepted track record and the Mission G historical ledgers are
returned as SEPARATE lanes with an explicit pooling prohibition; no field
ever carries their sum.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Optional

_ROOT = Path(__file__).resolve().parents[1]
_STATS = _ROOT / "stats"

CONTRACT_VERSION = "mission-g-evidence-v1"

G6A_READOUT_PATH = _STATS / "G6_FROZEN_MANIFEST_READOUT.md"
G6B_STABILITY_PATH = _STATS / "G6B_STABILITY_AND_FALSIFIERS.md"
G6C_CASES_PATH = _STATS / "G6C_REPRESENTATIVE_CASES.md"
G5_PROMOTION_PATH = _STATS / "G5_PROMOTION_PROOF.md"
G3B_ATTRITION_PATH = _STATS / "G3_MECHANISM_CLASSIFICATION_ATTRITION.md"

# Research-approved wording (interpretation, not a computed number). Its
# presence in the tracked G6C artifact is verified at build time.
APPROVED_OPEC_WORDING = ("stable descriptive association with unresolved "
                         "calendar-time confounding")
CASE_STATUS_WORDING = "illustrations, never proof"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"mission-g artifact unreadable: {path.name}: {exc}") from exc


def _search(pattern: str, text: str, artifact: str) -> re.Match:
    m = re.search(pattern, text, re.MULTILINE)
    if m is None:
        raise ValueError(
            f"mission-g artifact drift: {artifact} no longer matches "
            f"required pattern {pattern!r}; refusing to serve")
    return m


# ---------------------------------------------------------------------------
# Artifact parsers (every research number in the contract comes from here)
# ---------------------------------------------------------------------------


def _parse_accepted_count(g5_text: str) -> int:
    m = _search(r"^\| accepted track record before -> after \| "
                r"(\d+) -> (\d+) \|", g5_text, "G5_PROMOTION_PROOF.md")
    before, after = int(m.group(1)), int(m.group(2))
    if before != after:
        raise ValueError("mission-g artifact drift: accepted track record "
                         "changed across promotion in G5 proof")
    return after


def _parse_historical_lanes(g6a_text: str) -> dict[str, int]:
    fomc = int(_search(
        r"^\| frame_complete_historical \| fomc \| `fed_policy_path` \| "
        r"continuous \| (\d+) \|", g6a_text,
        "G6_FROZEN_MANIFEST_READOUT.md").group(1))
    opec = int(_search(
        r"^\| designed_contrast \| opec \| `fed_policy_path` \| "
        r"continuous \| (\d+) \|", g6a_text,
        "G6_FROZEN_MANIFEST_READOUT.md").group(1))
    m = _search(r"^- universe: frame (\d+) \+ designed (\d+) = (\d+);",
                g6a_text, "G6_FROZEN_MANIFEST_READOUT.md")
    total = int(m.group(3))
    if (int(m.group(1)), int(m.group(2))) != (fomc, opec) \
            or fomc + opec != total:
        raise ValueError("mission-g artifact drift: G6A universe line "
                         "disagrees with the denominator board")
    return {"fomc": fomc, "opec": opec, "total": total}


def _parse_credit_subsets(g6a_text: str) -> dict[str, int]:
    m = _search(r"^- credit era-bounded subsets: FOMC (\d+) / OPEC (\d+)",
                g6a_text, "G6_FROZEN_MANIFEST_READOUT.md")
    return {"fomc": int(m.group(1)), "opec": int(m.group(2))}


def _parse_stability(g6b_text: str) -> dict[str, int]:
    total = int(_search(
        r"every one of the (\d+) continuous entry x metric x horizon "
        r"associations", g6b_text,
        "G6B_STABILITY_AND_FALSIFIERS.md").group(1))
    loeo = int(_search(
        r"^- associations with at least one LOEO sign reversal: (\d+)",
        g6b_text, "G6B_STABILITY_AND_FALSIFIERS.md").group(1))
    loyo = int(_search(
        r"^- associations with at least one LOYO sign reversal: (\d+)",
        g6b_text, "G6B_STABILITY_AND_FALSIFIERS.md").group(1))
    return {"total": total, "loeo": loeo, "loyo": loyo}


def _parse_fomc_max_rho(g6b_text: str) -> float:
    return float(_search(
        r"largest absolute full-sample rho anywhere in that lane is "
        r"(\d+\.\d+)", g6b_text,
        "G6B_STABILITY_AND_FALSIFIERS.md").group(1))


def _parse_opec_association(g6b_text: str) -> list[dict[str, Any]]:
    rows = re.findall(
        r"^- OPEC `fed_policy_path` x sector-relative AR (\d+)d: rho "
        r"(-?\d+\.\d+); LOEO \[[^\]]+\], opposite (\d+); LOYO "
        r"\[[^\]]+\], opposite (\d+)", g6b_text, re.MULTILINE)
    if len(rows) != 3:
        raise ValueError(
            "mission-g artifact drift: expected three OPEC fed-path "
            f"falsifier rows in G6B, found {len(rows)}")
    return [{"horizon": int(h), "rho": float(rho),
             "loeo_sign_reversals": int(loeo),
             "loyo_sign_reversals": int(loyo)}
            for h, rho, loeo, loyo in rows]


def _parse_credit_fragility(g6c_text: str) -> dict[str, int]:
    m = _search(r"(\d+) of the (\d+) credit associations flip sign",
                g6c_text, "G6C_REPRESENTATIVE_CASES.md")
    return {"fragile": int(m.group(1)), "of": int(m.group(2))}


def _parse_g3b_coverage(g3b_text: str) -> dict[str, float]:
    def pct(label: str) -> float:
        return float(_search(
            rf"^- {label}: (\d+\.\d+)% classified", g3b_text,
            "G3_MECHANISM_CLASSIFICATION_ATTRITION.md").group(1))

    return {
        "accepted_news_headlines":
            pct(r"accepted track-record \(news headlines\)"),
        "fomc_official_text":
            pct(r"G1A FOMC historical \(official policy-action titles\)"),
        "opec_official_text":
            pct(r"G1B OPEC historical \(official decision titles\)"),
    }


def _provenance_entry(path: Path) -> dict[str, Any]:
    """Request-time artifact fingerprint — the same convention as the
    Mission I and Mission J contracts (the sha256 / byte size of the
    tracked artifact actually served)."""
    data = path.read_bytes()
    return {"artifact": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def _parse_reproduction_commands(text: str, artifact: str) -> list[str]:
    """The fenced command block under the publication's Reproduction
    heading — recorded in every Mission G publication, exposed verbatim
    (never hand-copied here).  Drift (no heading, no fence, or a
    non-command line) refuses to serve."""
    heading = re.search(
        r"^## (?:\d+\. )?(?:Provenance and )?[Rr]eproduction\s*$",
        text, re.MULTILINE)
    if heading is None:
        raise ValueError(
            f"mission-g artifact drift: {artifact} no longer records a "
            "Reproduction section; refusing to serve")
    fence = re.search(r"```\n([\s\S]*?)```", text[heading.end():])
    if fence is None:
        raise ValueError(
            f"mission-g artifact drift: {artifact} Reproduction section "
            "lost its command block; refusing to serve")
    commands = [line.rstrip() for line in fence.group(1).splitlines()
                if line.strip()]
    if not commands or not all(c.startswith("python ") for c in commands):
        raise ValueError(
            f"mission-g artifact drift: {artifact} reproduction commands "
            "drifted; refusing to serve")
    return commands


def _parse_case_slots(g6c_text: str) -> list[dict[str, str]]:
    rows = re.findall(
        r"^\| ([ABC]) \([^)]*\) \| (\S+) \| `(\w+)` \| (Q25|Q75) \| "
        r"[^|]+ \| `([a-z0-9-]+)` \|", g6c_text, re.MULTILINE)
    if len(rows) != 6:
        raise ValueError(
            "mission-g artifact drift: expected exactly six role slots in "
            f"the G6C selection ledger, found {len(rows)}")
    return [{"role": role, "lane": lane, "state_axis": axis,
             "quantile": quantile.lower(), "candidate_id": cid}
            for role, lane, axis, quantile, cid in rows]


# ---------------------------------------------------------------------------
# Contract builder
# ---------------------------------------------------------------------------


def build_mission_g_evidence_summary(
        *,
        g6a_path: Path | str = G6A_READOUT_PATH,
        g6b_path: Path | str = G6B_STABILITY_PATH,
        g6c_path: Path | str = G6C_CASES_PATH,
        g5_path: Path | str = G5_PROMOTION_PATH,
        g3b_path: Path | str = G3B_ATTRITION_PATH,
) -> dict[str, Any]:
    """The Mission G research record as a structured, read-only contract.

    Reads only the tracked artifacts given (defaults: the canonical
    ``stats/`` files). Raises ``ValueError`` on any artifact drift.
    """
    g6a = _read(Path(g6a_path))
    g6b = _read(Path(g6b_path))
    g6c = _read(Path(g6c_path))
    g5 = _read(Path(g5_path))
    g3b = _read(Path(g3b_path))

    accepted = _parse_accepted_count(g5)
    lanes = _parse_historical_lanes(g6a)
    credit_subsets = _parse_credit_subsets(g6a)
    stability = _parse_stability(g6b)
    opec_rows = _parse_opec_association(g6b)
    fragility = _parse_credit_fragility(g6c)
    coverage = _parse_g3b_coverage(g3b)
    slots = _parse_case_slots(g6c)

    # Research-approved wording must still be present in the artifact that
    # carries it (G6C is the canonical interpretation surface);
    # interpretation here never outlives its evidence.
    if APPROVED_OPEC_WORDING not in g6c:
        raise ValueError(
            "mission-g artifact drift: approved bounded-association "
            "wording is no longer present in the tracked G6C artifact")
    if CASE_STATUS_WORDING not in g6c:
        raise ValueError(
            "mission-g artifact drift: representative-case status wording "
            "is no longer present in the tracked G6C artifact")

    unique_case_ids: list[str] = []
    for slot in slots:
        if slot["candidate_id"] not in unique_case_ids:
            unique_case_ids.append(slot["candidate_id"])

    artifact_paths = {
        "readout": Path(g6a_path),
        "stability": Path(g6b_path),
        "cases": Path(g6c_path),
        "promotion_proof": Path(g5_path),
        "mechanism_attrition": Path(g3b_path),
    }
    artifact_texts = {"readout": g6a, "stability": g6b, "cases": g6c,
                      "promotion_proof": g5, "mechanism_attrition": g3b}

    return {
        "contract_version": CONTRACT_VERSION,
        "source_artifacts": {
            "readout": str(Path(g6a_path).name),
            "stability": str(Path(g6b_path).name),
            "cases": str(Path(g6c_path).name),
            "promotion_proof": str(Path(g5_path).name),
            "mechanism_attrition": str(Path(g3b_path).name),
        },
        "provenance": {
            "sources": {key: _provenance_entry(path)
                        for key, path in artifact_paths.items()},
            "reproduction": {
                # Recorded in every Mission G publication (each carries a
                # fenced Reproduction block); parsed verbatim at request
                # time, never hand-copied.
                "commands": {
                    key: _parse_reproduction_commands(
                        artifact_texts[key], path.name)
                    for key, path in artifact_paths.items()},
                "recorded_in": {key: path.name
                                for key, path in artifact_paths.items()},
            },
            # Recorded in NO Mission G publication — stated as null rather
            # than inferred from the checkout, Git HEAD, or the clock.
            "execution_commits": None,
            "computation_dates": None,
        },
        "lanes": {
            "accepted_track_record": {
                "count": accepted,
                "lane_note": ("separate immutable live-archive lineage "
                              "with its own denominator; it is not part "
                              "of the historical evidence below"),
            },
            "historical": {
                "total": lanes["total"],
                "fomc_frame_complete": lanes["fomc"],
                "opec_designed_contrast": lanes["opec"],
                "lane_note": ("two historical ledgers promoted under the "
                              "Mission G protocol; the designed-contrast "
                              "lane carries no prevalence claim"),
            },
            "pooling_prohibition": (
                "The accepted track record and the historical ledgers "
                "are separate denominators answering different questions; "
                "they are never pooled, summed, or compared as one "
                "sample."),
        },
        "main_result": {
            "headline": ("The historical state-conditioning surface is "
                         "predominantly flat, fragile, or contradictory "
                         "under the frozen manifest."),
            "fomc_null": {
                "statement": ("The frame-complete FOMC lane is broadly "
                              "null: no state axis holds a stable rank "
                              "association with any response lens."),
                "max_abs_full_sample_rho": _parse_fomc_max_rho(g6b),
            },
        },
        "stability": {
            "continuous_associations": stability["total"],
            "loeo_sign_reversals": stability["loeo"],
            "loyo_sign_reversals": stability["loyo"],
            "note": ("leave-one-event-out and leave-one-calendar-year-out "
                     "diagnostics were applied uniformly to every "
                     "association; surviving them is not validation"),
        },
        "bounded_opec_association": {
            "wording": APPROVED_OPEC_WORDING,
            "axis": "fed_policy_path x sector-relative abnormal return",
            "lane": "opec_designed_contrast",
            "per_horizon": opec_rows,
            "confound_note": ("the state axis itself tracks calendar "
                              "time inside this lane, so these data "
                              "cannot separate state from era"),
        },
        "credit_limitation": {
            "available": credit_subsets["fomc"] + credit_subsets["opec"],
            "of": lanes["total"],
            "fomc_subset": credit_subsets["fomc"],
            "opec_subset": credit_subsets["opec"],
            "era_bounded": True,
            "status": "secondary",
            "fragile_associations": fragility["fragile"],
            "of_associations": fragility["of"],
            "note": ("HY OAS history before the surviving source window "
                     "is source-withdrawn; the subset is descriptive "
                     "only and was not promoted after outcomes were "
                     "visible"),
        },
        "failed_thesis_mechanism_comparability": {
            "statement": ("A J1-derived headline mechanism taxonomy did "
                          "not transfer comparably across accepted news "
                          "headlines and historical official-decision "
                          "text; mechanism labels are not a cross-cohort "
                          "conditioning axis."),
            "classification_coverage_percent": coverage,
        },
        "representative_cases": {
            "role_slots": len(slots),
            "unique_cases": len(unique_case_ids),
            "status": CASE_STATUS_WORDING,
            "selection_note": ("state-quantile anchored, outcome-blind "
                               "selection; outcome magnitude was never "
                               "used"),
            "cases": slots,
        },
        "non_claims": [
            "Descriptive research record only: no p-values, no "
            "forecasts, no trading interpretation, no single-event "
            "inference.",
            "No pooled statistic across evidence lanes.",
            "Representative cases are illustrations, never proof.",
        ],
    }

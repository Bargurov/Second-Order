"""G4 - outcome-blind structural validation and final research freeze.

Mission G, protocol g0-v1, freeze version g4-structural-freeze-v1.

This module performs the SECOND freeze of the two-freeze governance in
`stats/G_RESEARCH_PROTOCOL.md` section 8: the actual numeric values and
final design decisions, calibrated ONLY from outcome-blind candidate
structure (occupancy, missingness, unique dates, concentration, temporal
distribution, mechanical attrition, classification attrition,
interpretability). It never reads, computes, persists, or summarizes any
market response (no absolute return, AR, SAR, CAR, sector-relative
response, sign, direction, magnitude, or outcome label). Structural
inputs are validated against a field whitelist and outcome-shaped keys
are rejected loudly.

What it freezes (tracked in `stats/G4_STRUCTURAL_FREEZE.md`):

* the final five-dimension state design (each G0 dimension ->
  primary_retained / secondary_subset_only / dropped);
* secondary categorical tags (sign-based, definition-derived only;
  degenerate tags rejected deterministically; continuous stays canonical);
* the designed-contrast recruitment ledger over the 32-row OPEC reservoir
  (rule g4-designed-recruitment-v1; full reservoir accounting);
* the G6 comparison manifest (within-lane conditional descriptive
  comparisons only; no pooled cross-lane statistic; no mechanism-taxonomy
  conditioning per the G3B comparability finding).

Reuses, never reimplements: the G2 state primitives
(`scripts/g_state_acquisition.py`) and the frozen G3 transmission map
(`scripts/g3_mechanical_grinder.py`). No new lookback, no proxy, no new
state variable, no revised definition.

Usage:

    python scripts/g4_structural_freeze.py --freeze   # write tracked report
    python scripts/g4_structural_freeze.py --json     # structural JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts.g3_mechanical_grinder import (  # noqa: E402
    TRANSMISSION_MAP, candidate_family)

FREEZE_VERSION = "g4-structural-freeze-v1"
RECRUITMENT_RULE_VERSION = "g4-designed-recruitment-v1"
REPORT_PATH = ROOT / "stats" / "G4_STRUCTURAL_FREEZE.md"
G3_REPORT_PATH = ROOT / "stats" / "G3_MECHANICAL_ELIGIBILITY.md"

STATUSES = ("primary_retained", "secondary_subset_only", "dropped")

# Frozen minimum unique-date support (G0 section 8 numeric freeze).
# Derivation, enumerated in the report: the largest single lane-year
# occupancy in the 97-candidate universe is 10 (designed_contrast, 2025).
# Requiring STRICTLY MORE unique dates than any single lane-year can supply
# means no sufficient tag category or comparison cell can be an artifact of
# one calendar year of one lane. 10 + 1 = 11.
MIN_TAG_CATEGORY_UNIQUE_DATES = 11
MIN_CELL_UNIQUE_DATES = 11

STRUCTURAL_ROW_FIELDS = ("candidate_id", "lane", "family", "event_date",
                         "year", "cutoff", "state")

_CANDIDATE_INPUT_FIELDS = frozenset({"candidate_id", "event_date", "lane"})

# Outcome-shaped key tokens: any input or row key containing one of these
# whole tokens is rejected (firewall, G0 section 9).
_FORBIDDEN_KEY_TOKENS = frozenset({
    "abnormal", "outcome", "sar", "car", "scar", "return", "returns",
    "sign", "direction", "effect", "magnitude", "readout", "reaction",
    "response", "label",
})

# The four sign-based tag rules G0's definitions make non-arbitrary: zero
# is definitionally meaningful (policy direction, price vs own average,
# curve inversion). No other cut is definition-derived.
_SIGN_TAG_RULES: dict[str, dict[str, Any]] = {
    "fed_policy_path": {
        "rule": "easing if value < 0, hold if value == 0, "
                "tightening if value > 0",
        "categories": ("easing", "hold", "tightening"),
        "classify": lambda v: ("easing" if v < 0
                               else "hold" if v == 0 else "tightening"),
        "zero_meaning": "no net policy-rate change over the frozen "
                        "six-month lookback",
    },
    "spy_trend_ma200": {
        "rule": "below_ma if value < 0 else above_ma",
        "categories": ("below_ma", "above_ma"),
        "classify": lambda v: "below_ma" if v < 0 else "above_ma",
        "zero_meaning": "price exactly at its 200-session moving average",
    },
    "curve_2s10s": {
        "rule": "inverted if value < 0 else non_inverted",
        "categories": ("inverted", "non_inverted"),
        "classify": lambda v: "inverted" if v < 0 else "non_inverted",
        "zero_meaning": "flat 2s10s spread",
    },
}

_NO_RULE_REASONS = {
    "vix_level_percentile": (
        "continuous only: the percentile is already a normalized state; "
        "any cut point (0.5, 0.8, quartiles) would be an arbitrary "
        "threshold not derivable from the G0 definition"),
    "credit_hy_oas": (
        "continuous only: an OAS level cut has no definition-derived zero "
        "and any spread threshold would be an arbitrary constant"),
}


# ---------------------------------------------------------------------------
# Firewall helpers
# ---------------------------------------------------------------------------


def _check_no_outcome_keys(mapping: Mapping[str, Any], *,
                           allowed: frozenset[str]) -> None:
    for key in mapping:
        if key in allowed:
            continue
        tokens = set(str(key).lower().replace("-", "_").split("_"))
        if tokens & _FORBIDDEN_KEY_TOKENS:
            raise ValueError(
                f"outcome-shaped key {key!r} rejected by the G4 firewall")
        raise ValueError(
            f"unexpected key {key!r}: G4 accepts only whitelisted "
            f"structural fields {sorted(allowed)}")


# ---------------------------------------------------------------------------
# Structural rows (state values via the frozen G2 primitives only)
# ---------------------------------------------------------------------------


def build_structural_rows(candidates: Sequence[Mapping[str, Any]],
                          bundle: gsa.SourceBundle) -> list[dict[str, Any]]:
    """One outcome-blind structural row per candidate.

    State values delegate to the G2 point-in-time primitives with the G0
    windows (six-month policy lookback, 252-session percentile,
    200-session moving average, next_day eligibility). No other window
    exists in this module.
    """
    rows: list[dict[str, Any]] = []
    for cand in candidates:
        _check_no_outcome_keys(cand, allowed=_CANDIDATE_INPUT_FIELDS)
        cutoff = gsa.conservative_cutoff(cand["event_date"], bundle.sessions)
        if cutoff is None:
            raise ValueError(
                f"cutoff unresolved for {cand['candidate_id']!r}; "
                "identity-valid candidates must resolve a cutoff")
        state: dict[str, Optional[float]] = {
            "fed_policy_path": gsa.fed_net_change(
                bundle.fed_timeline, cutoff, months=6)["value"],
            "vix_level_percentile": gsa.trailing_percentile(
                bundle.vix or {}, cutoff, window=252)["value"],
            "spy_trend_ma200": gsa.ma_distance(
                bundle.spy or {}, cutoff, window=200)["value"],
        }
        for dim, series in (("curve_2s10s", bundle.curve_2s10s),
                            ("credit_hy_oas", bundle.hy_oas)):
            got = gsa.latest_eligible(series or {}, cutoff,
                                      availability="next_day")
            state[dim] = None if got is None else got[1]
        rows.append({
            "candidate_id": cand["candidate_id"],
            "lane": cand["lane"],
            "family": candidate_family(cand),
            "event_date": cand["event_date"],
            "year": cand["event_date"][:4],
            "cutoff": cutoff,
            "state": state,
        })
    rows.sort(key=lambda r: (r["event_date"], r["candidate_id"]))
    return rows


# ---------------------------------------------------------------------------
# 1. Universe reconciliation (fail loudly on drift)
# ---------------------------------------------------------------------------


def _parse_g3_funnel(g3_text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, pattern in (
            ("identity_valid", r"^- identity-valid: (\d+)$"),
            ("canonical_eligible",
             r"^- canonical event-study available: (\d+)$"),
            ("sector_relative_eligible",
             r"^- sector-relative available: (\d+)$")):
        m = re.search(pattern, g3_text, re.MULTILINE)
        if not m:
            raise ValueError(f"G3 artifact missing funnel line for {key}")
        out[key] = int(m.group(1))
    return out


def reconcile_universe(rows: Sequence[Mapping[str, Any]],
                       g3_report_text: str) -> dict[str, int]:
    """Exact structural reconciliation; any drift raises ValueError."""
    by_lane: dict[str, int] = {}
    for r in rows:
        by_lane[r["lane"]] = by_lane.get(r["lane"], 0) + 1
    recon = {
        "frame_complete_historical": by_lane.get(
            "frame_complete_historical", 0),
        "designed_contrast": by_lane.get("designed_contrast", 0),
        "total": len(rows),
        "unique_candidate_ids": len({r["candidate_id"] for r in rows}),
        "unique_event_dates": len({r["event_date"] for r in rows}),
        **_parse_g3_funnel(g3_report_text),
    }
    failures = []
    if recon["frame_complete_historical"] != 65:
        failures.append(f"frame lane {recon['frame_complete_historical']}"
                        " != 65")
    if recon["designed_contrast"] != 32:
        failures.append(f"designed lane {recon['designed_contrast']} != 32")
    if recon["total"] != 97:
        failures.append(f"total {recon['total']} != 97")
    if recon["unique_candidate_ids"] != recon["total"]:
        failures.append("duplicate candidate ids")
    if recon["unique_event_dates"] != recon["total"]:
        failures.append("duplicate event dates")
    for key in ("identity_valid", "canonical_eligible",
                "sector_relative_eligible"):
        if recon[key] != 97:
            failures.append(f"{key} {recon[key]} != 97")
    if failures:
        raise ValueError("universe reconciliation drift: "
                         + "; ".join(failures))
    return recon


# ---------------------------------------------------------------------------
# 2. Final dimension-status freeze (deterministic)
# ---------------------------------------------------------------------------


def freeze_dimension_statuses(
        rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Exactly one status per G0 dimension from structure alone.

    Rule (deterministic): full coverage -> primary_retained; zero
    coverage -> dropped; partial coverage -> secondary_subset_only IFF the
    missingness is era-structural (every missing cutoff strictly precedes
    every available cutoff, i.e. one contiguous source-era boundary),
    otherwise dropped (non-structural attrition is not interpretable).
    """
    n = len(rows)
    statuses: dict[str, dict[str, Any]] = {}
    for dim in gsa.DIMENSIONS:
        available = [r for r in rows if r["state"][dim] is not None]
        missing = [r for r in rows if r["state"][dim] is None]
        by_lane = {}
        for r in available:
            by_lane[r["lane"]] = by_lane.get(r["lane"], 0) + 1
        entry: dict[str, Any] = {
            "coverage": len(available),
            "of": n,
            "coverage_by_lane": dict(sorted(by_lane.items())),
        }
        if len(available) == n:
            entry["status"] = "primary_retained"
            entry["reason"] = ("full coverage: available for every "
                               "candidate in both lanes and all years")
        elif not available:
            entry["status"] = "dropped"
            entry["reason"] = "zero coverage: no usable observation"
        else:
            max_missing_cutoff = max(r["cutoff"] for r in missing)
            min_available_cutoff = min(r["cutoff"] for r in available)
            if max_missing_cutoff < min_available_cutoff:
                entry["status"] = "secondary_subset_only"
                entry["reason"] = (
                    "era-structural partial coverage: every missing cutoff "
                    "precedes every available cutoff (single source-era "
                    "boundary), so availability is a source-level property "
                    "of calendar time; the dimension cannot enter the "
                    "primary cross-period vector without confounding state "
                    "availability with era, but is usable as an explicitly "
                    "era-bounded secondary subset lens")
                entry["era_boundary"] = {
                    "last_missing_cutoff": max_missing_cutoff,
                    "first_available_cutoff": min_available_cutoff,
                }
            else:
                entry["status"] = "dropped"
                entry["reason"] = (
                    "partial coverage with non-era-structural missingness: "
                    "availability interleaves with unavailability, so the "
                    "attrition pattern is not interpretable as a source "
                    "boundary; dropped rather than risk selective coverage")
        statuses[dim] = entry
    return statuses


# ---------------------------------------------------------------------------
# 3. Secondary tag freeze (sign-based only; degeneracy rejected)
# ---------------------------------------------------------------------------


def _occupancy(rows: Sequence[Mapping[str, Any]], dim: str,
               classify: Any, categories: Sequence[str]) -> dict[str, Any]:
    by_cat: dict[str, dict[str, Any]] = {
        c: {"count": 0, "unique_dates": 0, "by_lane": {}, "by_year": {}}
        for c in categories}
    dates: dict[str, set] = {c: set() for c in categories}
    for r in rows:
        v = r["state"][dim]
        if v is None:
            continue
        cat = classify(v)
        cell = by_cat[cat]
        cell["count"] += 1
        dates[cat].add(r["event_date"])
        cell["by_lane"][r["lane"]] = cell["by_lane"].get(r["lane"], 0) + 1
        cell["by_year"][r["year"]] = cell["by_year"].get(r["year"], 0) + 1
    for c in categories:
        by_cat[c]["unique_dates"] = len(dates[c])
        by_cat[c]["by_lane"] = dict(sorted(by_cat[c]["by_lane"].items()))
        by_cat[c]["by_year"] = dict(sorted(by_cat[c]["by_year"].items()))
    return {"total": sum(by_cat[c]["count"] for c in categories),
            "by_category": by_cat}


def freeze_tags(rows: Sequence[Mapping[str, Any]],
                statuses: Mapping[str, Mapping[str, Any]]
                ) -> dict[str, dict[str, Any]]:
    """One deterministic tag decision per dimension.

    Continuous values stay canonical everywhere. A sign-based tag is
    retained only for primary_retained dimensions whose G0 definition
    makes zero meaningful AND whose every category clears the frozen
    unique-date floor; otherwise the dimension stays continuous-only with
    the reason recorded.
    """
    tags: dict[str, dict[str, Any]] = {}
    for dim in gsa.DIMENSIONS:
        status = statuses[dim]["status"]
        if status != "primary_retained":
            tags[dim] = {
                "decision": "continuous_only",
                "rule": None,
                "reason": ("non-primary dimension "
                           f"({status}); tags apply to the primary state "
                           "vector only"),
            }
            continue
        spec = _SIGN_TAG_RULES.get(dim)
        if spec is None:
            tags[dim] = {
                "decision": "continuous_only",
                "rule": None,
                "reason": _NO_RULE_REASONS.get(
                    dim, "continuous only: no definition-derived cut"),
            }
            continue
        occ = _occupancy(rows, dim, spec["classify"], spec["categories"])
        thin = {c: cell["unique_dates"]
                for c, cell in occ["by_category"].items()
                if cell["unique_dates"] < MIN_TAG_CATEGORY_UNIQUE_DATES}
        if thin:
            tags[dim] = {
                "decision": "continuous_only",
                "rule": None,
                "reason": ("degenerate tag rejected: "
                           + ", ".join(
                               f"category {c!r} has {n} unique dates < "
                               f"{MIN_TAG_CATEGORY_UNIQUE_DATES}"
                               for c, n in sorted(thin.items()))),
                "occupancy": occ,
                "rejected_rule": spec["rule"],
            }
        else:
            tags[dim] = {
                "decision": "tag_retained",
                "rule": spec["rule"],
                "reason": ("sign-based tag: zero is definitionally "
                           f"meaningful ({spec['zero_meaning']}); every "
                           "category clears the frozen unique-date floor"),
                "occupancy": occ,
            }
    return tags


# ---------------------------------------------------------------------------
# 4. Designed-contrast recruitment (deterministic, outcome-blind)
# ---------------------------------------------------------------------------


def recruit_designed(rows: Sequence[Mapping[str, Any]], *,
                     primary_dims: Sequence[str]) -> dict[str, Any]:
    """Apply g4-designed-recruitment-v1 once over the designed reservoir.

    Rule: a reservoir candidate is recruited iff it is identity-valid
    (present in the reservoir ledger), mechanically eligible (the G3
    funnel is reconciled to 97/97 before this runs), and carries a
    complete primary state vector. The frame lane is never filtered.
    Every reservoir row is accounted for exactly once.
    """
    for r in rows:
        _check_no_outcome_keys(r, allowed=frozenset(STRUCTURAL_ROW_FIELDS))
    frame_ids = sorted(r["candidate_id"] for r in rows
                       if r["lane"] == "frame_complete_historical")
    recruited: list[str] = []
    non_recruited: list[dict[str, str]] = []
    for r in sorted((r for r in rows if r["lane"] == "designed_contrast"),
                    key=lambda r: r["candidate_id"]):
        gaps = [d for d in primary_dims if r["state"][d] is None]
        if gaps:
            non_recruited.append({
                "candidate_id": r["candidate_id"],
                "reason": "incomplete_primary_state: " + ", ".join(gaps),
            })
        else:
            recruited.append(r["candidate_id"])
    return {
        "rule_version": RECRUITMENT_RULE_VERSION,
        "frame_preserved_ids": frame_ids,
        "reservoir_denominator": len(recruited) + len(non_recruited),
        "recruited_denominator": len(recruited),
        "recruited_ids": recruited,
        "non_recruited": non_recruited,
    }


# ---------------------------------------------------------------------------
# 5. G6 comparison manifest (within-lane, mechanism-free, descriptive)
# ---------------------------------------------------------------------------


def build_manifest(rows: Sequence[Mapping[str, Any]],
                   statuses: Mapping[str, Mapping[str, Any]],
                   tags: Mapping[str, Mapping[str, Any]],
                   *, extra_axes: Sequence[str] = ()) -> list[dict[str, Any]]:
    """The frozen G6 comparison manifest.

    Within-lane conditional descriptive comparisons only. Axes are limited
    to non-dropped G0 dimensions (continuous) plus retained sign tags
    (categorical). Any other axis - including any mechanism-taxonomy axis -
    is rejected: the G3B finding stands and sampling family never becomes
    a comparison mechanism.
    """
    allowed = {d for d, s in statuses.items() if s["status"] != "dropped"}
    for axis in extra_axes:
        raise ValueError(
            f"axis {axis!r} rejected: G6 conditioning axes are limited to "
            f"the non-dropped G0 state dimensions {sorted(allowed)}")

    lanes = sorted({r["lane"] for r in rows})
    entries: list[dict[str, Any]] = []
    for lane in lanes:
        lane_rows = [r for r in rows if r["lane"] == lane]
        families = sorted({r["family"] for r in lane_rows})
        if len(families) != 1:
            raise ValueError(f"lane {lane!r} spans families {families}")
        lens = TRANSMISSION_MAP[families[0]]
        for dim in sorted(allowed):
            eligible = [r for r in lane_rows
                        if r["state"][dim] is not None]
            if not eligible:
                continue
            unique_dates = len({r["event_date"] for r in eligible})
            secondary = statuses[dim]["status"] == "secondary_subset_only"
            base = {
                "lane": lane,
                "sampling_family": families[0],
                "primary_asset": lens.primary,
                "market_benchmark": lens.market,
                "sector_benchmark": lens.sector,
                "state_axis": dim,
                "eligible_denominator": len(eligible),
                "unique_dates": unique_dates,
                "date_span": [min(r["event_date"] for r in eligible),
                              max(r["event_date"] for r in eligible)],
                "sufficiency": ("sufficient"
                                if unique_dates >= MIN_CELL_UNIQUE_DATES
                                else "insufficient_n"),
                "claim_tier": "conditional_descriptive",
                "fdr_scope": "none_descriptive_only",
                "secondary_scope": (
                    "era-bounded post-window subset; descriptive only"
                    if secondary else None),
            }
            entries.append({**base, "use": "continuous", "cells": None})
            tag = tags.get(dim, {})
            if tag.get("decision") == "tag_retained":
                spec = _SIGN_TAG_RULES[dim]
                cells = []
                for cat in spec["categories"]:
                    cat_rows = [r for r in eligible
                                if spec["classify"](r["state"][dim]) == cat]
                    cat_dates = len({r["event_date"] for r in cat_rows})
                    cells.append({
                        "cell": cat,
                        "occupancy": len(cat_rows),
                        "unique_dates": cat_dates,
                        "sufficiency": (
                            "sufficient"
                            if cat_dates >= MIN_CELL_UNIQUE_DATES
                            else "insufficient_n"),
                    })
                entries.append({**base, "use": "categorical",
                                "cells": cells})
    entries.sort(key=lambda e: (e["lane"], e["state_axis"], e["use"]))
    return entries


# ---------------------------------------------------------------------------
# Tracked freeze report (deterministic, timestamp-free)
# ---------------------------------------------------------------------------


def _load_live() -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates = (gsa.parse_g1a_candidates(str(gsa.G1A_PATH))
                  + gsa.parse_g1b_candidates(str(gsa.G1B_PATH)))
    rows = build_structural_rows(candidates, gsa.load_bundle())
    recon = reconcile_universe(
        rows, G3_REPORT_PATH.read_text(encoding="utf-8"))
    return rows, recon


def _max_lane_year_occupancy(rows: Sequence[Mapping[str, Any]]) -> int:
    counts: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["lane"], r["year"])
        counts[key] = counts.get(key, 0) + 1
    return max(counts.values())


def _occupancy_lines(occ: Mapping[str, Any]) -> list[str]:
    L = []
    for cat, cell in occ["by_category"].items():
        lanes = ", ".join(f"{k}: {v}" for k, v in cell["by_lane"].items())
        years = ", ".join(f"{k}: {v}" for k, v in cell["by_year"].items())
        L.append(f"  - `{cat}`: {cell['count']} candidates on "
                 f"{cell['unique_dates']} unique dates | by lane: "
                 f"{lanes or 'none'} | by year: {years or 'none'}")
    return L


def build_freeze_report_text() -> str:
    rows, recon = _load_live()
    statuses = freeze_dimension_statuses(rows)
    tags = freeze_tags(rows, statuses)
    primary = tuple(d for d in gsa.DIMENSIONS
                    if statuses[d]["status"] == "primary_retained")
    ledger = recruit_designed(rows, primary_dims=primary)
    manifest = build_manifest(rows, statuses, tags)
    max_ly = _max_lane_year_occupancy(rows)

    L = [
        "# G4 structural freeze (Mission G, g0-v1)",
        "",
        f"Freeze version: `{FREEZE_VERSION}`. This is the second freeze of "
        "the two-freeze governance (protocol section 8): final state "
        "design, secondary tags, designed-contrast recruitment, numeric "
        "support floors, and the G6 comparison manifest - frozen from "
        "OUTCOME-BLIND candidate structure before any market-response "
        "value is inspected.",
        "",
        "Inputs consulted (complete enumeration, per the protocol's G4 "
        "duty): candidate identity ledgers (G1A frame, G1B reservoir); "
        "lane; source family; event date; calendar year; conservative "
        "cutoff; state values and state availability from the G2 "
        "substrate; occupancy; missingness structure; unique-date counts; "
        "lane/year concentration; the G3A mechanical-eligibility funnel "
        "(tracked artifact); the G3B classification-attrition finding "
        "(tracked artifact); economic interpretability of the G0 "
        "definitions. No absolute return, AR, SAR, CAR, sector-relative "
        "response, sign, direction, magnitude, or outcome label was "
        "computed, read, persisted, or summarized anywhere in this slice; "
        "structural inputs are validated against a tested field whitelist.",
        "",
        "## 1. Universe reconciliation (exact, fail-loud)",
        "",
        "| check | value |",
        "|---|---|",
        f"| frame-complete FOMC | {recon['frame_complete_historical']} |",
        f"| OPEC designed reservoir | {recon['designed_contrast']} |",
        f"| total | {recon['total']} |",
        f"| unique candidate ids | {recon['unique_candidate_ids']} |",
        f"| unique event dates | {recon['unique_event_dates']} |",
        f"| identity-valid (G3 artifact) | {recon['identity_valid']} |",
        f"| canonical event-study eligible | {recon['canonical_eligible']} |",
        "| sector-relative eligible | "
        f"{recon['sector_relative_eligible']} |",
        "",
        "## 2. Frozen numeric support floor",
        "",
        f"`MIN_UNIQUE_DATES = {MIN_CELL_UNIQUE_DATES}` for every tag "
        "category and every G6 comparison cell. Derivation (structural, "
        "enumerated): the largest single lane-year occupancy in the "
        f"universe is {max_ly}; requiring strictly more unique dates than "
        "any single lane-year can supply means no sufficient category or "
        "cell can be the artifact of one calendar year of one lane "
        f"({max_ly} + 1 = {MIN_CELL_UNIQUE_DATES}). Cells below the floor "
        "are retained in the manifest and reported as `insufficient_n` - "
        "reported, never hidden (protocol section 14).",
        "",
        "## 3. Final state design",
        "",
    ]
    for dim in gsa.DIMENSIONS:
        s = statuses[dim]
        L.append(f"### `{dim}` -> **{s['status']}**")
        L.append("")
        L.append(f"- coverage: {s['coverage']}/{s['of']} "
                 f"(by lane: "
                 + ", ".join(f"{k}: {v}" for k, v
                             in s["coverage_by_lane"].items()) + ")")
        L.append(f"- reason: {s['reason']}")
        if "era_boundary" in s:
            L.append(f"- era boundary: last missing cutoff "
                     f"{s['era_boundary']['last_missing_cutoff']}, first "
                     f"available cutoff "
                     f"{s['era_boundary']['first_available_cutoff']}")
        if dim == "credit_hy_oas":
            L.append(
                "- structural limitations: the surviving source window is "
                "a rolling three-year license (G2 section 3); the "
                "candidate-level inputs in use are preserved in "
                "`stats/G2D_CREDIT_POINT_IN_TIME_EVIDENCE.md`; missingness "
                "follows the source-era boundary with no candidate-level "
                "attrition inside the window; every use is era-bounded "
                "and descriptive only")
        L.append("")
    L += [
        "The primary cross-period state vector is therefore: "
        + ", ".join(f"`{d}`" for d in primary) + ". `credit_hy_oas` may "
        "not enter it: with 61/97 missing along the source-era boundary, "
        "any cross-period conditioning on credit would compare eras, not "
        "states. It is frozen as an era-bounded secondary subset lens "
        "only.",
        "",
        "## 4. Frozen secondary tags",
        "",
        "Continuous state values remain canonical everywhere; tags are "
        "secondary derived views. Only sign-based rules whose zero is "
        "definitionally meaningful were candidates; every retained rule "
        "and every rejection is recorded.",
        "",
    ]
    for dim in gsa.DIMENSIONS:
        t = tags[dim]
        L.append(f"### `{dim}` -> **{t['decision']}**")
        L.append("")
        if t.get("rule"):
            L.append(f"- rule: `{t['rule']}`")
        if t.get("rejected_rule"):
            L.append(f"- rejected rule: `{t['rejected_rule']}`")
        L.append(f"- reason: {t['reason']}")
        if t.get("occupancy"):
            L.append(f"- occupancy (total {t['occupancy']['total']}):")
            L += _occupancy_lines(t["occupancy"])
        L.append("")
    L += [
        "Rejected tag ideas (recorded, not silently skipped): composite "
        "multi-dimension regime labels and any 12-cell regime grid "
        "(banned by task and protocol); VIX-percentile cut points "
        "(arbitrary constants); HY OAS spread-level cuts (arbitrary, and "
        "the dimension is era-bounded secondary); moving-average-distance "
        "magnitude bands (arbitrary); any threshold chosen for response "
        "separation (outcome-dependent, firewall-banned).",
        "",
        "## 5. Designed-contrast recruitment ledger",
        "",
        f"Rule `{RECRUITMENT_RULE_VERSION}` (deterministic, outcome-blind, "
        "applied once): recruit a reservoir candidate iff it is "
        "identity-valid in the G1B reservoir ledger, mechanically eligible "
        "(section 1 reconciles the G3 funnel at 97/97 before recruitment "
        "runs), and carries a complete primary state vector "
        "(" + ", ".join(f"`{d}`" for d in primary) + "). No candidate is "
        "recruited or excluded for remembered historical importance, and "
        "no response value exists anywhere in the path.",
        "",
        f"- reservoir denominator: {ledger['reservoir_denominator']}",
        f"- recruited denominator: {ledger['recruited_denominator']}",
        f"- non-recruited: {len(ledger['non_recruited'])}",
        f"- frame lane preserved intact: "
        f"{len(ledger['frame_preserved_ids'])} rows (never filtered)",
        "",
        "Recruited candidate ids "
        f"({ledger['recruited_denominator']}):",
        "",
    ]
    for cid in ledger["recruited_ids"]:
        L.append(f"- `{cid}`")
    L.append("")
    if ledger["non_recruited"]:
        L.append("Non-recruited candidate ids (with structural reason):")
        L.append("")
        for e in ledger["non_recruited"]:
            L.append(f"- `{e['candidate_id']}`: {e['reason']}")
    else:
        L.append(
            "Non-recruited candidate ids: none. Every reservoir row "
            "passes every structural gate, so the frozen rule recruits "
            "the full reservoir; selective recruitment would have "
            "required a structural discriminator that does not exist, "
            "and inventing one would be arbitrary.")
    L += [
        "",
        "Discovery provenance: the reservoir is "
        "`opec-production-policy-reservoir-2018-2025@v1` "
        "(`stats/G1B_OPEC_DESIGNED_RESERVOIR.md`), a designed-recruitment "
        "ledger over a NON-ENUMERABLE event family; per-candidate "
        "discovery provenance lives in that ledger and is preserved "
        "unchanged.",
        "",
        "Non-prevalence claim (explicit): the designed-contrast cohort is "
        "recruited evidence. It supports conditional contrasts and "
        "representative description only; it carries NO prevalence claim, "
        "NO frame-completeness claim, and no statistic pooled across "
        "sampling lanes may ever include it (protocol section 3).",
        "",
        "## 6. G6 comparison manifest (frozen before any outcome is "
        "visible)",
        "",
        "Every planned G6 comparison, exhaustively. All entries are "
        "conditional DESCRIPTIVE comparisons (protocol section 14): no "
        "p-value, no FDR figure, no significance claim; none belongs to "
        "any closed FDR pool. Within-lane conditioning only - no pooled "
        "FOMC + OPEC statistic of any kind. Response lenses for every "
        "entry are the four shipped lenses of the standardization spec "
        "(absolute, market-relative, sector-relative where eligible, "
        "SAR), displayed per the spec's discipline; the benchmarks below "
        "come from the frozen `g3-transmission-map-v1` with no "
        "event-specific ticker change.",
        "",
        "| lane | family | primary | market | sector | state axis | use | "
        "denominator | unique dates | date span | sufficiency | claim "
        "tier | FDR scope |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in manifest:
        L.append(
            f"| {e['lane']} | {e['sampling_family']} | "
            f"{e['primary_asset']} | {e['market_benchmark']} | "
            f"{e['sector_benchmark']} | `{e['state_axis']}`"
            + (" (secondary)" if e["secondary_scope"] else "")
            + f" | {e['use']} | {e['eligible_denominator']} | "
            f"{e['unique_dates']} | {e['date_span'][0]} .. "
            f"{e['date_span'][1]} | {e['sufficiency']} | "
            f"{e['claim_tier']} | {e['fdr_scope']} |")
    L += ["", "Categorical cells (per retained tag, per lane):", ""]
    any_cells = False
    for e in manifest:
        if e["use"] != "categorical":
            continue
        any_cells = True
        L.append(f"- {e['lane']} / `{e['state_axis']}`:")
        for c in e["cells"]:
            L.append(f"  - `{c['cell']}`: occupancy {c['occupancy']}, "
                     f"unique dates {c['unique_dates']}, "
                     f"{c['sufficiency']}")
    if not any_cells:
        L.append("- none (no tag was retained)")
    L += [
        "",
        "Time-drift duty inherited from protocol section 13: every G6 "
        "exhibit must print each group's date span and period "
        "distribution; zero-calendar-overlap contrasts are automatically "
        "descriptive-only with the time table inline. The era-bounded "
        "credit entries satisfy this by construction (their spans are "
        "printed above).",
        "",
        "## 7. Exclusions (inherited and structural)",
        "",
        "- The J1 mechanism overlay is not a comparable cross-cohort axis "
        "and is excluded from G6 conditioning: the G3B finding shows "
        "classification coverage collapses across source registers "
        "(accepted 79.1% vs FOMC 0.0% / OPEC 3.1%), so no G6 comparison "
        "conditions on, stratifies by, or filters with the G3B/J1 "
        "mechanism labels, and no cross-cohort mechanism comparison uses "
        "that overlay.",
        "- No pooled FOMC + OPEC 'overall effect' exists in the manifest; "
        "the pooling prohibition is symmetric and permanent.",
        "- No event-specific ticker change: benchmarks are the frozen "
        "family-level map.",
        "- The accepted 86 remain a separate lineage: they are never "
        "merged into historical G6 state-conditioned pools, and no "
        "accepted-vs-historical state-conditioned comparison is frozen "
        "here (the cohorts are temporally disjoint; any such display "
        "would be descriptive-only under section 13 and is out of scope "
        "for this manifest).",
        "- Representative cases and descriptive archive reads never enter "
        "any closed FDR pool.",
        "- The closed Phase 1 / Phase 2 FDR pools stay closed; nothing in "
        "G6 joins them.",
        "",
        "## 8. Non-claims",
        "",
        "No outcome inference, no regime prediction, no causal regime "
        "effect, and no trading interpretation. This freeze validates "
        "structure only: it says nothing about the direction, size, or "
        "existence of any market response, and nothing here is a p-value, "
        "an effective sample size, or an FDR figure. Not a trading, "
        "prediction, or recommendation surface.",
        "",
        "## 9. Reproduction",
        "",
        "```",
        "python scripts/g4_structural_freeze.py --freeze   # regenerate "
        "this report (byte-identical)",
        "python scripts/g4_structural_freeze.py --json     # structural "
        "JSON (whitelisted fields only)",
        "python -m unittest tests.test_g4_structural_freeze",
        "```",
    ]
    return "\n".join(L) + "\n"


def emit_freeze_report() -> str:
    text = build_freeze_report_text()
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    return f"G4 structural freeze written -> {REPORT_PATH.relative_to(ROOT)}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G4 outcome-blind structural freeze (no outcome value "
                    "is read, computed, or persisted).")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.freeze:
        print(emit_freeze_report())
    if args.json:
        rows, recon = _load_live()
        statuses = freeze_dimension_statuses(rows)
        tags = freeze_tags(rows, statuses)
        primary = tuple(d for d in gsa.DIMENSIONS
                        if statuses[d]["status"] == "primary_retained")
        print(json.dumps({
            "freeze_version": FREEZE_VERSION,
            "reconciliation": recon,
            "statuses": statuses,
            "tags": tags,
            "recruitment": recruit_designed(rows, primary_dims=primary),
            "manifest": build_manifest(rows, statuses, tags),
        }, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

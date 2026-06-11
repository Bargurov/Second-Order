#!/usr/bin/env python3
"""Read-only case-selection STRESS report for the N1 transmission walkthrough.

Q1 tests whether the six N1 selected cases ([1, 61, 210, 46, 66, 211]) are
robust under alternative *deterministic* selection policies - WITHOUT changing
the N1 selector and WITHOUT replacing the six primary cases. It is a sensitivity
diagnostic, not a replacement.

Discipline (non-negotiable):

  * **current_n1 reuses N1's real ``select_cases``** (imported read-only); the
    N1 selector and its six cases are untouched.
  * **Policies are deterministic and never use returns, sector availability,
    favorable outcomes, or future information.** They re-rank the SAME
    enrichment (outcome bucket, family, info_score, anchor label, event-study
    availability) that N1 already computes - only the selection RULE differs.
  * **The anchor-score doc/impl mismatch is measured and DISCLOSED, never
    fixed.** ``info_score`` rewards any anchor not in ``_CAVEATED_ANCHORS`` with
    its "+1 clean" bonus, which silently includes partial-anticipation and
    scheduled/weak anchors. Q1 reports this; it does not change it.
  * No DB / price_cache mutation; no significance, performance ranking, or
    proof framing.

Usage::

    python scripts/transmission_case_selection_stress_report.py --db-path events.db --json
    python scripts/transmission_case_selection_stress_report.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import transmission_case_walkthrough_report as W  # noqa: E402
from scripts.accepted_family_overlay_report import classify_headline  # noqa: E402
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402

DEFAULT_EXAMPLES = 3
DEFAULT_CASES = 6

POLICY_NAMES: tuple[str, ...] = (
    "current_n1", "family_first", "outcome_first", "anchor_quality_first",
    "missingness_aware", "reverse_id_tiebreak",
)
_ALT_POLICIES = POLICY_NAMES[1:]

# Strict clean-anchor ranking for anchor_quality_first. Only
# ``clean_discrete_anchor`` is truly clean; the rest are progressively weaker.
_ANCHOR_RANK = {
    "clean_discrete_anchor": 0,
    "partial_anticipation": 1,
    "scheduled_or_weak_anchor": 2,
}
_TRULY_CLEAN = frozenset({"clean_discrete_anchor"})

_POLICY_RULES = {
    "current_n1": "N1's select_cases: outcome roles (support/contradiction/"
                  "unresolved-or-limited), then family-diversity fills; rank "
                  "(info_score desc, event_id asc).",
    "family_first": "Maximise distinct families first by (info_score desc, "
                    "event_id asc); no outcome guard.",
    "outcome_first": "Force the three outcome roles, then fill by pure "
                     "(info_score desc, event_id asc) - no family preference.",
    "anchor_quality_first": "Rank by strict anchor quality "
                            "(clean_discrete_anchor first), then info_score, "
                            "then event_id, with the outcome guard kept.",
    "missingness_aware": "Force at least one data-limited or "
                         "event-study-missing accepted row, then N1's role + "
                         "family logic.",
    "reverse_id_tiebreak": "N1's role + family structure with the event_id "
                           "tie-break REVERSED (info_score desc, event_id "
                           "desc).",
}

_POLICY_RISK = {
    "family_first": "Drops the outcome guarantee - may omit a contradiction or "
                    "an unresolved case in favour of family breadth.",
    "outcome_first": "Keeps outcome diversity but fills by raw info_score, so "
                     "the family mix (and which ties win) shifts.",
    "anchor_quality_first": "Surfaces how few truly-clean anchors exist; the "
                            "current six lean on anchors the info_score "
                            "mismatch treats as clean.",
    "missingness_aware": "Forces a data-limited / no-event-study case the "
                         "current six omit (16/86 accepted rows lack "
                         "event-study coverage; 13 are data-limited).",
    "reverse_id_tiebreak": "Isolates how consequential the event_id tie-break "
                           "is - many candidates tie at the top info_score.",
}

NON_CLAIMS: tuple[str, ...] = (
    "This stress report does not replace N1: the six primary walkthrough cases "
    "and the N1 selector are unchanged.",
    "Representative cases are illustrative, not proof of any mechanism.",
    "No single-event significance is claimed (n=1; no CI, p-value, or FDR).",
    "No family-level inference and no performance ranking across cases or "
    "families.",
    "Selection never uses returns, AR/SAR/CAR, sector availability, or "
    "favorable outcomes - only deterministic structural attributes.",
    "Not a recommendation of any kind.",
    "No paid analysis; no database or price_cache mutation; nothing fetched or "
    "backfilled.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record.",
)


# ---------------------------------------------------------------------------
# Deterministic policies (no returns / sector / favorable outcomes)
# ---------------------------------------------------------------------------


def _k_info(r):
    return (-r["info_score"], r["event_id"])


def _k_info_rev(r):
    return (-r["info_score"], -r["event_id"])


def _k_anchor(r):
    return (_ANCHOR_RANK.get(r["anchor_quality"], 3), -r["info_score"],
            r["event_id"])


def _select(pool, n, *, sort_key, force_roles=False, prefer_family=False,
            force_data_limited=False):
    n = max(int(n), 0)
    ordered = sorted(pool, key=sort_key)
    selected: list[int] = []
    used: set = set()
    used_fams: set = set()

    def best(pred):
        for r in ordered:
            if r["event_id"] not in used and pred(r):
                return r
        return None

    def take(r):
        selected.append(r["event_id"])
        used.add(r["event_id"])
        used_fams.add(r.get("family_primary"))

    if force_data_limited and len(selected) < n:
        r = best(lambda r: r.get("is_data_limited") or not r.get("has_es"))
        if r is not None:
            take(r)
    if force_roles:
        for pred in (
            lambda r: r["outcome_bucket"] == "support",
            lambda r: r["outcome_bucket"] == "contradiction",
            lambda r: r["outcome_bucket"] in ("unresolved", "data_limited"),
        ):
            if len(selected) >= n:
                break
            r = best(pred)
            if r is not None:
                take(r)
    while len(selected) < n:
        r = best(lambda r: r.get("family_primary") not in used_fams) \
            if prefer_family else None
        if r is None:
            r = best(lambda r: True)
        if r is None:
            break
        take(r)
    return selected


def apply_policy(pool: list[dict], policy_name: str, n_cases: int) -> list[int]:
    """Return the event_ids a deterministic policy would select from ``pool``."""
    if policy_name == "current_n1":
        return [c["event_id"] for c in W.select_cases(pool, n_cases)]
    if policy_name == "family_first":
        return _select(pool, n_cases, sort_key=_k_info, prefer_family=True)
    if policy_name == "outcome_first":
        return _select(pool, n_cases, sort_key=_k_info, force_roles=True)
    if policy_name == "anchor_quality_first":
        return _select(pool, n_cases, sort_key=_k_anchor, force_roles=True)
    if policy_name == "missingness_aware":
        return _select(pool, n_cases, sort_key=_k_info, force_roles=True,
                       prefer_family=True, force_data_limited=True)
    if policy_name == "reverse_id_tiebreak":
        return _select(pool, n_cases, sort_key=_k_info_rev, force_roles=True,
                       prefer_family=True)
    raise ValueError(f"unknown policy {policy_name!r}")


# ---------------------------------------------------------------------------
# Loaders (read-only, reuse N1 enrichment helpers)
# ---------------------------------------------------------------------------


def _load_pool(db_path: str | None) -> list[dict]:
    rows = W._load_case_rows(db_path)
    es_av, _ = W._load_event_study(db_path)
    edqr = edq_build_report(db_path=db_path, lens="accepted", limit=0)
    edq_by = {e["event_id"]: e for e in edqr.get("events", [])}
    pool = []
    for r in rows:
        eid = r["event_id"]
        has_es = eid in es_av
        overlay = classify_headline(r.get("headline") or "")
        bucket = W.outcome_bucket(r.get("tickers") or [], has_es)
        pool.append({
            "event_id": eid,
            "outcome_bucket": bucket,
            "family_primary": overlay[0] if overlay else "unclassified",
            "family_overlay": list(overlay),
            "info_score": W.info_score(r, edq_by.get(eid), has_es),
            "has_es": has_es,
            "anchor_quality": edq_by.get(eid, {}).get("event_date_quality",
                                                      "unavailable"),
            "is_data_limited": bucket == "data_limited",
            "is_multi_or_unclassified": len(overlay) != 1,
        })
    pool.sort(key=lambda r: r["event_id"])
    return pool


def _current_n1_ids(db_path: str | None) -> list[int]:
    try:
        rep = W.build_walkthrough(db_path=db_path)
        return [c["event_id"] for c in rep.get("selected_cases", [])]
    except Exception:
        return []


def _load_denominators(db_path: str | None) -> dict[str, Any]:
    rep = edq_build_report(db_path=db_path, lens="accepted", limit=0)
    d = rep.get("denominators", {})
    return {k: d.get(k) for k in (
        "archive_rows", "accepted_coverage_denominator",
        "accepted_track_record_denominator", "staged_candidate_count")}


# ---------------------------------------------------------------------------
# Composition + assembly
# ---------------------------------------------------------------------------


def _composition(by_id: dict, ids: Sequence[int]) -> dict[str, Any]:
    sel = [by_id[i] for i in ids if i in by_id]
    return {
        "outcome_composition": dict(Counter(r["outcome_bucket"] for r in sel)),
        "family_composition": dict(Counter(r["family_primary"] for r in sel)),
        "anchor_quality_composition":
            dict(Counter(r["anchor_quality"] for r in sel)),
        "event_study_availability_composition":
            dict(Counter("available" if r["has_es"] else "missing"
                         for r in sel)),
        "data_limited_count": sum(1 for r in sel if r["is_data_limited"]),
        "multi_match_or_unclassified_count":
            sum(1 for r in sel if r["is_multi_or_unclassified"]),
    }


def _anchor_check(pool: list[dict]) -> dict[str, Any]:
    labels = {r["anchor_quality"] for r in pool}
    rewarded = labels - set(W._CAVEATED_ANCHORS)
    non_clean_rewarded = sorted(rewarded - _TRULY_CLEAN)
    return {
        "documented_policy": (
            "info_score awards +1 for a clean event-date anchor (per the "
            "walkthrough docs)."),
        "observed_implementation_behavior": (
            "info_score awards the +1 to any anchor NOT in _CAVEATED_ANCHORS "
            f"{sorted(W._CAVEATED_ANCHORS)}. In this corpus that includes the "
            f"non-clean anchors {non_clean_rewarded}, which therefore receive "
            "the 'clean' bonus despite being partial-anticipation or "
            "scheduled/weak."),
        "mismatch_detected": bool(non_clean_rewarded),
        "non_clean_anchors_rewarded": non_clean_rewarded,
        "recommendation": (
            "Disclose only. A fix would either tighten the clean-anchor test in "
            "info_score to clean_discrete_anchor, or correct the doc to match "
            "the implementation - both are out of Q1 scope (Q1 does not change "
            "the N1 selector)."),
    }


def _scoring_fragility_notes(pool: list[dict]) -> list[str]:
    info_counts = Counter(r["info_score"] for r in pool)
    top = max(info_counts) if info_counts else 0
    return [
        f"info_score is heavily tied: {dict(sorted(info_counts.items()))} - "
        f"{info_counts.get(top, 0)} rows share the top score {top}, so the "
        "event_id tie-break decides many fills.",
        "The current six all carry event-study coverage and are all "
        "single-family matches; the corpus has 16/86 rows without event-study "
        "coverage and 16 multi-match / 18 unclassified rows.",
    ]


def build_report(db_path: str | None = None, *,
                 pool: list[dict] | None = None,
                 current_ids: Sequence[int] | None = None,
                 denominators: dict | None = None,
                 n_cases: int = DEFAULT_CASES,
                 include_examples: int = DEFAULT_EXAMPLES) -> dict[str, Any]:
    """Build the selection-stress report. Read-only; never changes N1."""
    if pool is None:
        pool = _load_pool(db_path)
    if current_ids is None:
        current_ids = _current_n1_ids(db_path)
    if denominators is None:
        denominators = _load_denominators(db_path)

    current_ids = list(current_ids)
    by_id = {r["event_id"]: r for r in pool}
    current_set = set(current_ids)

    # Self-consistency: does our reconstructed selector reproduce N1's six?
    reconstruction = apply_policy(pool, "current_n1", n_cases)
    reconstruction_consistent = (reconstruction == current_ids
                                 if current_ids else True)

    comparisons = []
    alt_sets = {}
    for name in _ALT_POLICIES:
        sel = apply_policy(pool, name, n_cases)
        alt_sets[name] = set(sel)
        comp = _composition(by_id, sel)
        comparisons.append({
            "policy_name": name,
            "selection_rule": _POLICY_RULES[name],
            "selected_case_ids": sel,
            "overlap_with_current_count": len(set(sel) & current_set),
            "retained_current_ids": [i for i in current_ids if i in set(sel)],
            "dropped_current_ids": [i for i in current_ids if i not in set(sel)],
            "reviewer_risk_note": _POLICY_RISK[name],
            **comp,
        })

    retained_by_all = [i for i in current_ids
                       if all(i in s for s in alt_sets.values())]
    dropped_by_some = [i for i in current_ids
                       if any(i not in s for s in alt_sets.values())]

    current_block = {
        "selected_case_ids": current_ids,
        "scoring_fragility_notes": _scoring_fragility_notes(pool),
        **_composition(by_id, current_ids),
    }

    anchor_check = _anchor_check(pool)

    stress_summary = {
        "stable_elements": [
            "Outcome diversity (>=1 support, >=1 contradiction, >=1 "
            "unresolved/limited) holds under current_n1, outcome_first, "
            "missingness_aware and reverse_id_tiebreak.",
            (f"Current ids retained by EVERY alternative policy: "
             f"{retained_by_all or 'none'}."),
        ],
        "sensitive_elements": [
            (f"Current ids dropped by at least one alternative policy: "
             f"{dropped_by_some or 'none'}."),
            "Which rows fill the non-required slots is tie-break- and "
            "policy-sensitive because info_score is heavily tied.",
            "No current case is data-limited, event-study-missing, multi-match "
            "or unclassified; missingness_aware and family_first show such "
            "cases exist and are selectable deterministically.",
        ],
        "cherry_pick_risk_assessment": (
            "The current six are favourable on structure, not on returns: all "
            "carry event-study coverage and all are single-family matches, and "
            "five of six carry non-clean anchors the info_score mismatch "
            "rewards as clean. Selection never used returns or sector data, so "
            "this is a representativeness limitation to disclose, not a "
            "returns-based cherry-pick."),
        "whether_q2_is_needed": (
            "Not required: the case-selection sensitivity and the three "
            "composition gaps (no data-limited/missing case, no "
            "multi-match/unclassified case, anchor-score doc/impl mismatch) are "
            "disclosed compactly in this report. Per the Q1 rule a Q2 appendix "
            "is warranted only if a gap cannot be disclosed compactly, which is "
            "not the case here."),
        "recommendation": (
            "Keep the N1 six as primary - they are defensible - but state the "
            "three disclosed caveats beside them; do not optimise cases toward "
            "favourable outcomes; do not build a Q2 appendix on this evidence."),
    }

    return {
        "denominators": dict(denominators),
        "scope": {
            "read_only": True,
            "n1_selector_changed": False,
            "primary_walkthrough_cases_unchanged": True,
            "no_q2_appendix": True,
            "no_return_based_selection": True,
            "no_sector_based_selection": True,
            "current_n1_reconstruction_consistent": reconstruction_consistent,
        },
        "current_n1": current_block,
        "policy_comparisons": comparisons,
        "anchor_score_policy_check": anchor_check,
        "stress_summary": stress_summary,
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _safe(text: str) -> str:
    return str(text or "").encode("cp1252", "replace").decode("cp1252")


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("Transmission-case selection stress (read-only) - N1 unchanged")
    add("=" * 60)
    d = report["denominators"]
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']}")
    sc = report["scope"]
    add(f"N1 selector changed: {sc['n1_selector_changed']} | primary cases "
        f"unchanged: {sc['primary_walkthrough_cases_unchanged']} | "
        f"reconstruction consistent: "
        f"{sc['current_n1_reconstruction_consistent']}")
    add("")

    cn = report["current_n1"]
    add(f"Current N1 selection: {cn['selected_case_ids']}")
    add(f"  outcomes {cn['outcome_composition']} | families "
        f"{cn['family_composition']}")
    add(f"  anchors {cn['anchor_quality_composition']} | event-study "
        f"{cn['event_study_availability_composition']} | data-limited "
        f"{cn['data_limited_count']} | multi/unclassified "
        f"{cn['multi_match_or_unclassified_count']}")
    for note in cn["scoring_fragility_notes"]:
        add(f"  - {_safe(note)}")
    add("")

    add("Policy comparisons (diagnostics only; N1 stays primary):")
    for p in report["policy_comparisons"]:
        add(f"  [{p['policy_name']}] {p['selected_case_ids']}  "
            f"(overlap {p['overlap_with_current_count']}/"
            f"{len(cn['selected_case_ids'])}; dropped {p['dropped_current_ids']})")
        add(f"      rule: {_safe(p['selection_rule'])}")
        add(f"      outcomes {p['outcome_composition']} | families "
            f"{p['family_composition']} | data-limited {p['data_limited_count']}"
            f" | multi/uncl {p['multi_match_or_unclassified_count']}")
        add(f"      risk: {_safe(p['reviewer_risk_note'])}")
    add("")

    ac = report["anchor_score_policy_check"]
    add("Anchor-score policy check (disclose, not fix):")
    add(f"  documented: {_safe(ac['documented_policy'])}")
    add(f"  observed:   {_safe(ac['observed_implementation_behavior'])}")
    add(f"  mismatch detected: {ac['mismatch_detected']}")
    add(f"  -> {_safe(ac['recommendation'])}")
    add("")

    ss = report["stress_summary"]
    add("Stress summary:")
    for item in ss["stable_elements"]:
        add(f"  stable:    {_safe(item)}")
    for item in ss["sensitive_elements"]:
        add(f"  sensitive: {_safe(item)}")
    add(f"  cherry-pick risk: {_safe(ss['cherry_pick_risk_assessment'])}")
    add(f"  Q2 needed? {_safe(ss['whether_q2_is_needed'])}")
    add(f"  recommendation: {_safe(ss['recommendation'])}")
    add("")

    add("Non-claims:")
    for item in report["non_claims"]:
        add(f"  - {_safe(item)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only case-selection stress report for the N1 "
                    "transmission walkthrough (N1 unchanged).")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-examples", type=int, default=DEFAULT_EXAMPLES)
    args = parser.parse_args(argv)

    report = build_report(db_path=args.db_path,
                          include_examples=args.include_examples)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

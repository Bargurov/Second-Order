#!/usr/bin/env python3
"""Section C filter rule proposal generator.

Reads the Section C diagnostic outputs and produces a concrete
proposed filter plan for the Daily, Weekly, and Still Moving Market
surfaces.  **The plan is a proposal, not an implementation.**  This
script never applies, changes, or removes any production filter and
never mutates an existing artifact.

Inputs (each optional; missing files surface as a warning and
continue with empty evidence)::

    artifacts/section_c_source_inventory.json
    artifacts/section_c_daily_quality_diagnostic.json
    artifacts/section_c_weekly_duplicate_diagnostic.json
    artifacts/section_c_still_moving_quality_diagnostic.json
    artifacts/section_c_quality_diagnostic.json

Read-only by construction
-------------------------

* Every input is a JSON file under ``artifacts/``.  The script reads
  with ``Path.read_text`` only.  No DB connection is opened, no
  archive / news / cache file is touched, no provider / yfinance /
  LLM / FastAPI surface is imported.
* No production filter module (``api`` / ``routes.*`` /
  ``movers_cache``) is bound at module import — the diagnostic and
  the proposal it derives must remain decoupled from the live
  pipeline so the proposal can describe what to change without
  re-entering the live filter.
* ``--output`` is the only filesystem side effect, and it refuses
  to overwrite an existing path so an existing proposal artifact is
  never silently rewritten.

Output JSON shape::

    {
      "ok":                          bool,
      "generated_at":                str,            # ISO-8601 UTC
      "daily_filter_proposals":      [rule, ...],
      "weekly_filter_proposals":     [rule, ...],
      "still_moving_filter_proposals": [rule, ...],
      "cross_section_rules":         [rule, ...],
      "highest_impact_rules":        [rule, ...],
      "rules_not_recommended_yet":   [rule, ...],
      "evidence_from_diagnostics":   {
        "source_inventory":          {"present": bool, "counts": {...}},
        "daily":                     {"present": bool, "counts": {...}},
        "weekly":                    {"present": bool, "counts": {...}},
        "still_moving":              {"present": bool, "counts": {...}},
        "combined":                  {"present": bool, "counts": {...}},
      },
      "warnings":                    [str, ...],
      "errors":                      [str, ...],
    }

Per-rule shape (the 8 spec fields)::

    {
      "rule_id":                       str,
      "section":                       "daily" | "weekly" |
                                        "still_moving" | "global",
      "description":                   str,
      "diagnostic_evidence":           {
        "source_diagnostic":           str,
        "evidence_count":              int,
        "sample_event_ids":            [int, ...],     # ≤5
        "evidence_note":               str,
      },
      "expected_benefit":              str,
      "possible_false_positive_risk":  str,
      "implementation_complexity":     "low" | "medium" | "high",
      "priority":                      "high" | "medium" | "low",
    }

Priority assignment
-------------------

* ``cross_section_rules`` G1 (missing mechanism family) and G2
  (weak ticker proxy) are pinned ``high`` per the spec.
* Section-specific rules use evidence count thresholds:
  ``high`` ≥ 50, ``medium`` ≥ 10, ``low`` < 10 (including 0).
* ``highest_impact_rules`` is the subset of all proposed rules with
  ``priority == 'high'``, sorted by evidence count descending.

Conservative wording — banned tokens in any prose the proposal
emits: ``proof``, ``proven``, ``validated``, ``automatically``,
``alpha generated``, ``guaranteed``, ``correct ticker``.  Every
rule description starts with one of the suggestion verbs in
``_SUGGESTION_VERBS`` so the proposal never tells the system what
to do.

Usage::

    python scripts/section_c_filter_rule_proposal.py --json
    python scripts/section_c_filter_rule_proposal.py --json \\
        --combined-diagnostic artifacts/section_c_quality_diagnostic.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_ARTIFACT_TYPE: str = "section_c_filter_rule_proposal"


# ---------------------------------------------------------------------------
# Default input paths.  Missing files become warnings, not errors.
# ---------------------------------------------------------------------------

_DEFAULT_SOURCE_INVENTORY_PATH: str = \
    "artifacts/section_c_source_inventory.json"
_DEFAULT_DAILY_DIAGNOSTIC_PATH: str = \
    "artifacts/section_c_daily_quality_diagnostic.json"
_DEFAULT_WEEKLY_DIAGNOSTIC_PATH: str = \
    "artifacts/section_c_weekly_duplicate_diagnostic.json"
_DEFAULT_STILL_MOVING_DIAGNOSTIC_PATH: str = \
    "artifacts/section_c_still_moving_quality_diagnostic.json"
_DEFAULT_COMBINED_DIAGNOSTIC_PATH: str = \
    "artifacts/section_c_quality_diagnostic.json"


# ---------------------------------------------------------------------------
# Section identifiers and the suggestion-verb invariant.
# ---------------------------------------------------------------------------

_SECTION_DAILY:        str = "daily"
_SECTION_WEEKLY:       str = "weekly"
_SECTION_STILL_MOVING: str = "still_moving"
_SECTION_GLOBAL:       str = "global"


_SUGGESTION_VERBS: tuple[str, ...] = (
    "Consider",
    "Operators may",
    "Investigate",
)


# Priority thresholds for section-specific rules.  Global pinned-
# high rules ignore these — they are always ``high``.
_PRIORITY_HIGH_THRESHOLD:   int = 50
_PRIORITY_MEDIUM_THRESHOLD: int = 10


# Sample size for ``diagnostic_evidence.sample_event_ids``.  Kept
# small so the proposal stays inspectable.
_SAMPLE_EVENT_LIMIT: int = 5


# ---------------------------------------------------------------------------
# Rule templates — IDs, sections, descriptions, complexity, and the
# specific diagnostic list each rule reads its evidence from.
#
# The order in this tuple is the order rules appear in the per-
# section lists.  Tests pin a subset of IDs but tolerate additions.
# ---------------------------------------------------------------------------


_RULE_TEMPLATES: tuple[dict[str, Any], ...] = (
    # Daily ------------------------------------------------------------------
    {
        "rule_id":     "daily.require_mechanism_family",
        "section":     _SECTION_DAILY,
        "description": (
            "Consider requiring a non-null, non-'none' "
            "mechanism_family before a candidate is admitted to "
            "the Daily Section C surface, or routing missing-"
            "mechanism candidates through an enrichment step "
            "first."
        ),
        "evidence_source": "daily.missing_mechanism_cases",
        "expected_benefit": (
            "Daily surface stops admitting events whose mechanism "
            "label is missing or set to 'none', which would "
            "remove a known source of low-information rows."
        ),
        "possible_false_positive_risk": (
            "Events whose mechanism_family is genuinely 'none' but "
            "still market-relevant would be deferred; the rule "
            "should pair with an operator-review path before any "
            "blanket exclusion."
        ),
        "implementation_complexity": "low",
    },
    {
        "rule_id":     "daily.flag_off_topic_headlines",
        "section":     _SECTION_DAILY,
        "description": (
            "Consider deprioritising candidates whose headline "
            "matches the off-topic pattern bank (recipe, "
            "obituary, cooking, fashion-week, etc.) for the Daily "
            "surface, with operator review for borderline cases."
        ),
        "evidence_source": "daily.off_topic_cases",
        "expected_benefit": (
            "Headlines that are not market-relevant stop entering "
            "the Daily surface, which would remove visible junk "
            "from the operator's daily worklist."
        ),
        "possible_false_positive_risk": (
            "Legitimate headlines that mention an off-topic term "
            "(e.g. luxury-stocks pieces that mention 'fashion "
            "week') could be over-flagged; the pattern bank should "
            "stay narrow and observational, not auto-exclude."
        ),
        "implementation_complexity": "low",
    },
    {
        "rule_id":     "daily.flag_raw_legal_text",
        "section":     _SECTION_DAILY,
        "description": (
            "Consider deprioritising candidates whose headline "
            "matches the raw-legal-text pattern bank (§, Sec. N, "
            "Section N.N, CFR, USC, subparagraph/subsection, "
            "pursuant to, promulgated) for the Daily surface."
        ),
        "evidence_source": "daily.raw_legal_text_cases",
        "expected_benefit": (
            "Statute fragments and admin-page boilerplate stop "
            "presenting as market headlines on the Daily surface."
        ),
        "possible_false_positive_risk": (
            "Legitimate regulatory news headlines that quote a "
            "section reference would be flagged; operators should "
            "treat this as observational, not auto-exclude."
        ),
        "implementation_complexity": "low",
    },
    {
        "rule_id":     "daily.flag_low_market_relevance",
        "section":     _SECTION_DAILY,
        "description": (
            "Investigate candidates whose coarse market_relevance "
            "score sits below 0.7, indicating four or more "
            "weakness tags coinciding; route those to operator "
            "review rather than directly to the Daily surface."
        ),
        "evidence_source": "combined.low_market_relevance_count",
        "expected_benefit": (
            "Multi-issue candidates (several weakness tags at "
            "once) stop entering the Daily surface without a "
            "second pair of eyes."
        ),
        "possible_false_positive_risk": (
            "Real events whose coarse-heuristic score happens to "
            "dip below the threshold could be deferred; the score "
            "is intentionally coarse and should not be the only "
            "gate."
        ),
        "implementation_complexity": "medium",
    },

    # Weekly -----------------------------------------------------------------
    {
        "rule_id":     "weekly.collapse_repeated_headline_clusters",
        "section":     _SECTION_WEEKLY,
        "description": (
            "Consider collapsing candidates whose normalised "
            "headlines are exact matches inside the same weekly "
            "window into a single canonical row on the Weekly "
            "surface, preserving the dedupe-group_id pointer "
            "from the diagnostic."
        ),
        "evidence_source": "weekly.repeated_headline_groups",
        "expected_benefit": (
            "Weekly surface stops admitting near-identical "
            "headline reprints as separate rows, which would "
            "remove the duplicate-cards pattern operators have "
            "called out."
        ),
        "possible_false_positive_risk": (
            "A correctly-re-issued update on the same headline "
            "across consecutive days could be collapsed; the "
            "canonical selection rule should preserve a pointer "
            "to the collapsed event_ids so the operator can "
            "expand the group on demand."
        ),
        "implementation_complexity": "medium",
    },
    {
        "rule_id":     "weekly.collapse_date_ticker_duplicates",
        "section":     _SECTION_WEEKLY,
        "description": (
            "Consider collapsing candidates that share both "
            "event_date and primary_ticker within the weekly "
            "window into a single canonical row, even when their "
            "headlines differ — the date+ticker repetition is "
            "diagnostic of the same underlying story."
        ),
        "evidence_source": "weekly.repeated_date_ticker_groups",
        "expected_benefit": (
            "Reduces multi-headline retellings of the same "
            "(date, ticker) story to one row on the Weekly "
            "surface."
        ),
        "possible_false_positive_risk": (
            "Two distinct same-day, same-ticker stories (rare but "
            "possible) would be collapsed; operators should "
            "review the diagnostic's duplicate-group pointer "
            "before treating the collapse as automatic."
        ),
        "implementation_complexity": "medium",
    },
    {
        "rule_id":     "weekly.canonical_event_selection",
        "section":     _SECTION_WEEKLY,
        "description": (
            "Operators may want to define a canonical-event "
            "selection rule for duplicate groups (e.g. lowest "
            "event_id, earliest event_date, longest headline) "
            "before any collapse is applied — the diagnostic "
            "surfaces a suggested_canonical_event_id but the "
            "tiebreak policy is an operator decision."
        ),
        "evidence_source": "weekly.canonical_headline_suggestions",
        "expected_benefit": (
            "Makes the weekly collapse rule deterministic and "
            "reviewable: every collapsed group points to one "
            "canonical event by a documented tiebreak."
        ),
        "possible_false_positive_risk": (
            "A poorly-chosen tiebreak (e.g. lowest event_id) "
            "could systematically surface the earliest filing "
            "even when a later headline is more readable; the "
            "rule should be revisitable, not frozen."
        ),
        "implementation_complexity": "high",
    },

    # Still Moving -----------------------------------------------------------
    {
        "rule_id":     "still_moving.require_price_cache",
        "section":     _SECTION_STILL_MOVING,
        "description": (
            "Consider requiring local price_cache coverage for a "
            "candidate's primary_ticker before admitting it to "
            "the Still Moving Market surface; without cache rows "
            "no descriptive sensitivity statement can be backed "
            "by data."
        ),
        "evidence_source": "still_moving.missing_price_cache_cases",
        "expected_benefit": (
            "Still Moving surface stops featuring tickers for "
            "which no local price evidence exists, which would "
            "remove a class of unfounded persistence claims."
        ),
        "possible_false_positive_risk": (
            "Tickers that recently joined the universe and have "
            "not yet been cached would be deferred; the rule "
            "should pair with a backfill request so the deferral "
            "is recoverable."
        ),
        "implementation_complexity": "low",
    },
    {
        "rule_id":     "still_moving.require_benchmark_adjusted_evidence",
        "section":     _SECTION_STILL_MOVING,
        "description": (
            "Consider requiring benchmark-adjusted evidence "
            "(primary minus benchmark return statistic) before a "
            "candidate is admitted to the Still Moving Market "
            "surface; raw-price persistence without a benchmark "
            "comparison can reflect broad-market drift."
        ),
        "evidence_source": "still_moving.bad_proxy_cases",
        "expected_benefit": (
            "Persistence claims on Still Moving become "
            "descriptively defensible — a move that mirrors the "
            "benchmark is no longer counted as ticker-specific "
            "persistence."
        ),
        "possible_false_positive_risk": (
            "A primary ticker that lacks a matched benchmark in "
            "the cache would be deferred even when the persistence "
            "is real; the rule should pair with a benchmark "
            "preflight."
        ),
        "implementation_complexity": "medium",
    },
    {
        "rule_id":     "still_moving.require_persistence_signal",
        "section":     _SECTION_STILL_MOVING,
        "description": (
            "Consider requiring a persistence_signal of "
            "Accelerating or Holding before a candidate is "
            "admitted to the Still Moving Market surface; "
            "candidates with a null or Decaying persistence "
            "signal do not match the surface's stated intent."
        ),
        "evidence_source": "still_moving.no_persistence_cases",
        "expected_benefit": (
            "Still Moving Market surface stops featuring events "
            "that have already lost their move; the surface "
            "matches its label."
        ),
        "possible_false_positive_risk": (
            "Recently-arrived events whose persistence has not "
            "been computed yet would be deferred; the rule should "
            "pair with a clear 'not yet measured' status so the "
            "deferral is not confused with rejection."
        ),
        "implementation_complexity": "medium",
    },
    {
        "rule_id":     "still_moving.exclude_weak_ticker",
        "section":     _SECTION_STILL_MOVING,
        "description": (
            "Operators may want to gate Still Moving admission on "
            "ticker_quality being neither missing_primary nor "
            "no_cache; weak ticker rows produce a persistence "
            "claim with no underlying ticker to defend."
        ),
        "evidence_source": "still_moving.weak_ticker_cases",
        "expected_benefit": (
            "Removes the structural class of rows where the "
            "persistence statistic has nothing to attach to."
        ),
        "possible_false_positive_risk": (
            "Genuine events with a not-yet-cached ticker would "
            "be deferred; the rule should pair with the "
            "price_cache requirement rather than duplicate it."
        ),
        "implementation_complexity": "low",
    },

    # Cross-section / Global -------------------------------------------------
    {
        "rule_id":     "global.require_mechanism_family",
        "section":     _SECTION_GLOBAL,
        "description": (
            "Consider requiring a non-null, non-'none' "
            "mechanism_family across every Section C surface "
            "(Daily, Weekly, Still Moving Market).  The "
            "diagnostic reports missing_mechanism_family as the "
            "most-common quality issue across the cohort."
        ),
        "evidence_source": "combined.missing_mechanism_count",
        "expected_benefit": (
            "Section C surfaces stop admitting rows whose "
            "mechanism label is missing, which would remove a "
            "cross-cutting source of low-information cards."
        ),
        "possible_false_positive_risk": (
            "Events whose mechanism is mis-labelled 'none' "
            "upstream would be excluded; the rule should pair "
            "with an enrichment-or-review path so the deferral "
            "is recoverable."
        ),
        "implementation_complexity": "medium",
        "priority_pinned": "high",
    },
    {
        "rule_id":     "global.exclude_weak_ticker_proxy",
        "section":     _SECTION_GLOBAL,
        "description": (
            "Consider deprioritising candidates whose "
            "primary_ticker is a broad-market or sector-broad "
            "ETF (SPY, QQQ, IWM, DIA, VTI, XLE, XLF, XLP, XLK, "
            "XLV, XLI, XLY, XLU, XLB, XLRE, XLC) across every "
            "Section C surface; these are often pipeline "
            "fallbacks rather than the operator's intended "
            "primary."
        ),
        "evidence_source": "combined.bad_proxy_count",
        "expected_benefit": (
            "Section C surfaces stop featuring rows where the "
            "primary_ticker is a generic ETF acting as a "
            "fallback for a specific event."
        ),
        "possible_false_positive_risk": (
            "Genuinely sector-wide events (e.g., a Fed-driven "
            "sector rotation) would lose their broad-ETF "
            "primary; the rule should be observational on those "
            "rare events, not auto-exclude."
        ),
        "implementation_complexity": "low",
        "priority_pinned": "high",
    },
)


# Rules the proposal explicitly defers — observational only, too
# risky, or too complex to enact without further design work.
_RULES_NOT_RECOMMENDED_YET: tuple[dict[str, Any], ...] = (
    {
        "rule_id":     "deferred.vague_diplomacy_auto_exclude",
        "section":     _SECTION_GLOBAL,
        "description": (
            "Investigate whether candidates flagged with the "
            "vague_diplomacy tag warrant a dedicated filter.  The "
            "pattern bank is narrow on purpose and the tag is "
            "observational; auto-excluding may over-flag real "
            "policy statements."
        ),
        "diagnostic_evidence": {
            "source_diagnostic": "combined.vague_diplomacy",
            "evidence_count":    0,
            "sample_event_ids":  [],
            "evidence_note": (
                "Counts are tracked by section_c_daily_quality_"
                "diagnostic; the proposal defers the filter "
                "until the operator has reviewed a sample."
            ),
        },
        "expected_benefit": (
            "Could remove diplomatic-hedge filler from the "
            "Section C surfaces, pending a sample review."
        ),
        "possible_false_positive_risk": (
            "High — legitimate policy statements often use "
            "hedge language; the rule needs an operator-curated "
            "vocabulary, not a hard-coded pattern bank."
        ),
        "implementation_complexity": "medium",
        "priority":                  "low",
    },
    {
        "rule_id":     "deferred.auto_canonical_event_selection",
        "section":     _SECTION_WEEKLY,
        "description": (
            "Investigate whether the canonical-event selection "
            "rule for duplicate groups can be applied without "
            "operator review.  The diagnostic surfaces a "
            "suggested_canonical_event_id but the tiebreak "
            "policy is policy-level, not heuristic."
        ),
        "diagnostic_evidence": {
            "source_diagnostic": "weekly.canonical_headline_suggestions",
            "evidence_count":    0,
            "sample_event_ids":  [],
            "evidence_note": (
                "The weekly diagnostic surfaces canonical "
                "suggestions; this proposal defers the "
                "auto-application of those suggestions until "
                "the tiebreak policy is documented."
            ),
        },
        "expected_benefit": (
            "Could remove the operator-in-the-loop step from "
            "the weekly collapse rule, once the tiebreak is "
            "agreed."
        ),
        "possible_false_positive_risk": (
            "High — auto-selecting a representative without an "
            "operator-agreed tiebreak could systematically "
            "surface a less-informative row."
        ),
        "implementation_complexity": "high",
        "priority":                  "low",
    },
    {
        "rule_id":     "deferred.auto_low_market_relevance_exclude",
        "section":     _SECTION_GLOBAL,
        "description": (
            "Investigate whether the coarse market_relevance "
            "score is reliable enough to drive an outright "
            "exclusion rather than an operator-review nudge.  "
            "The score is intentionally coarse (10 features in "
            "0.1 bands) and was not designed to be the sole "
            "gate."
        ),
        "diagnostic_evidence": {
            "source_diagnostic": "combined.low_market_relevance",
            "evidence_count":    0,
            "sample_event_ids":  [],
            "evidence_note": (
                "The combined diagnostic flags candidates with "
                "score < 0.7; auto-excluding from Section C is "
                "deferred until the score's false-positive "
                "rate is measured."
            ),
        },
        "expected_benefit": (
            "Could remove multi-issue candidates without an "
            "operator step."
        ),
        "possible_false_positive_risk": (
            "High — the score is a coarse 10-feature sum and a "
            "single missed feature drops a candidate into the "
            "low band; the score should remain an operator-"
            "review nudge until calibrated."
        ),
        "implementation_complexity": "medium",
        "priority":                  "low",
    },
)


# ---------------------------------------------------------------------------
# Patchable seam — tests inject synthetic payloads.
# ---------------------------------------------------------------------------


def _load_diagnostic_payloads(
    *,
    source_inventory_path:        str | None,
    daily_diagnostic_path:        str | None,
    weekly_diagnostic_path:       str | None,
    still_moving_diagnostic_path: str | None,
    combined_diagnostic_path:     str | None,
) -> dict[str, Any]:
    """Read up to five diagnostic JSON outputs read-only.

    Returns a dict with the five payloads keyed by short source
    names (``source_inventory``, ``daily``, ``weekly``,
    ``still_moving``, ``combined``) plus ``warnings``/``errors``
    lists.  Missing files surface as a warning and the payload
    becomes ``None``; malformed JSON surfaces as an error.

    Tests patch this attribute directly so the import only resolves
    on the un-patched path.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    payloads: dict[str, dict[str, Any] | None] = {}
    for name, path in (
        ("source_inventory", source_inventory_path),
        ("daily",            daily_diagnostic_path),
        ("weekly",           weekly_diagnostic_path),
        ("still_moving",     still_moving_diagnostic_path),
        ("combined",         combined_diagnostic_path),
    ):
        payloads[name] = _safe_load_json(
            name=name, path=path,
            warnings=warnings, errors=errors,
        )

    return {
        **payloads,
        "warnings": warnings,
        "errors":   errors,
    }


def _safe_load_json(
    *,
    name:     str,
    path:     str | None,
    warnings: list[str],
    errors:   list[str],
) -> dict[str, Any] | None:
    """Read one diagnostic JSON.  Missing file → warning + None.
    Malformed JSON → error + None.  Non-dict payload → warning +
    None."""
    if not path:
        warnings.append(
            f"no path supplied for diagnostic input {name!r}; "
            f"the proposal proceeds with empty evidence for it"
        )
        return None
    target = Path(path)
    if not target.exists():
        warnings.append(
            f"diagnostic input {name!r} not found at {path!r}; "
            f"the proposal proceeds with empty evidence for it"
        )
        return None
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(
            f"failed to read diagnostic input {name!r} at {path!r}: {exc}"
        )
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(
            f"failed to parse diagnostic input {name!r} at {path!r}: {exc}"
        )
        return None
    if not isinstance(parsed, dict):
        warnings.append(
            f"diagnostic input {name!r} at {path!r} is not a JSON "
            f"object; ignoring"
        )
        return None
    return parsed


# ---------------------------------------------------------------------------
# Patchable seam — UTC clock.
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_section_c_filter_rule_proposal(
    *,
    source_inventory_path:        str | None = _DEFAULT_SOURCE_INVENTORY_PATH,
    daily_diagnostic_path:        str | None = _DEFAULT_DAILY_DIAGNOSTIC_PATH,
    weekly_diagnostic_path:       str | None = _DEFAULT_WEEKLY_DIAGNOSTIC_PATH,
    still_moving_diagnostic_path: str | None = _DEFAULT_STILL_MOVING_DIAGNOSTIC_PATH,
    combined_diagnostic_path:     str | None = _DEFAULT_COMBINED_DIAGNOSTIC_PATH,
    output_path:                  str | None = None,
    generated_at:                 str | None = None,
) -> dict[str, Any]:
    """Build the Section C filter rule proposal.

    See module docstring for the full output contract.
    """
    loaded = _load_diagnostic_payloads(
        source_inventory_path=source_inventory_path,
        daily_diagnostic_path=daily_diagnostic_path,
        weekly_diagnostic_path=weekly_diagnostic_path,
        still_moving_diagnostic_path=still_moving_diagnostic_path,
        combined_diagnostic_path=combined_diagnostic_path,
    )
    warnings: list[str] = list(loaded.get("warnings") or [])
    errors:   list[str] = list(loaded.get("errors") or [])

    payload_by_source: dict[str, dict[str, Any] | None] = {
        k: loaded.get(k) for k in (
            "source_inventory", "daily", "weekly",
            "still_moving", "combined",
        )
    }

    evidence_index = _build_evidence_index(
        payloads=payload_by_source,
    )

    daily_proposals:        list[dict[str, Any]] = []
    weekly_proposals:       list[dict[str, Any]] = []
    still_moving_proposals: list[dict[str, Any]] = []
    cross_section_rules:    list[dict[str, Any]] = []

    for tmpl in _RULE_TEMPLATES:
        rule = _build_rule_from_template(
            template=tmpl, evidence_index=evidence_index,
        )
        section = rule["section"]
        if section == _SECTION_DAILY:
            daily_proposals.append(rule)
        elif section == _SECTION_WEEKLY:
            weekly_proposals.append(rule)
        elif section == _SECTION_STILL_MOVING:
            still_moving_proposals.append(rule)
        elif section == _SECTION_GLOBAL:
            cross_section_rules.append(rule)

    all_rules = (
        daily_proposals + weekly_proposals
        + still_moving_proposals + cross_section_rules
    )
    highest_impact_rules = sorted(
        (r for r in all_rules if r["priority"] == "high"),
        key=lambda r: (
            -int(r["diagnostic_evidence"]["evidence_count"]),
            r["rule_id"],
        ),
    )

    evidence_from_diagnostics = _build_evidence_summary(
        payloads=payload_by_source,
    )

    envelope: dict[str, Any] = {
        "ok":                            not errors,
        "generated_at":                  generated_at or _utcnow_iso(),
        "daily_filter_proposals":        daily_proposals,
        "weekly_filter_proposals":       weekly_proposals,
        "still_moving_filter_proposals": still_moving_proposals,
        "cross_section_rules":           cross_section_rules,
        "highest_impact_rules":          highest_impact_rules,
        "rules_not_recommended_yet":     [
            dict(r) for r in _RULES_NOT_RECOMMENDED_YET
        ],
        "evidence_from_diagnostics":     evidence_from_diagnostics,
        "warnings":                      warnings,
        "errors":                        errors,
    }

    if output_path:
        write_err = _maybe_write_output(envelope, output_path)
        if write_err:
            envelope["errors"].append(write_err)
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Evidence indexing — turn the five diagnostic payloads into a
# single lookup keyed by ``evidence_source`` rule-template tokens.
# ---------------------------------------------------------------------------


def _build_evidence_index(
    *,
    payloads: dict[str, dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    """Resolve each ``evidence_source`` rule token to a
    ``(count, sample_event_ids, note)`` triple."""
    daily = payloads.get("daily") or {}
    weekly = payloads.get("weekly") or {}
    still_moving = payloads.get("still_moving") or {}
    combined = payloads.get("combined") or {}

    out: dict[str, dict[str, Any]] = {}

    # Daily diagnostic ------------------------------------------------------
    out["daily.missing_mechanism_cases"] = _summarise_list(
        daily.get("missing_mechanism_cases"),
        source="daily.missing_mechanism_cases",
        note="rows the daily diagnostic flagged as missing mechanism_family",
    )
    out["daily.off_topic_cases"] = _summarise_list(
        daily.get("off_topic_cases"),
        source="daily.off_topic_cases",
        note="rows the daily diagnostic flagged with the off_topic tag",
    )
    out["daily.raw_legal_text_cases"] = _summarise_list(
        daily.get("raw_legal_text_cases"),
        source="daily.raw_legal_text_cases",
        note="rows the daily diagnostic flagged with the raw_legal_text tag",
    )
    out["daily.duplicate_cases"] = _summarise_list(
        daily.get("duplicate_cases"),
        source="daily.duplicate_cases",
        note="rows the daily diagnostic flagged as duplicates within the daily window",
    )

    # Weekly diagnostic -----------------------------------------------------
    out["weekly.repeated_headline_groups"] = _summarise_groups(
        weekly.get("repeated_headline_groups"),
        source="weekly.repeated_headline_groups",
        note="groups the weekly diagnostic flagged as repeated-headline clusters",
    )
    out["weekly.repeated_date_ticker_groups"] = _summarise_groups(
        weekly.get("repeated_date_ticker_groups"),
        source="weekly.repeated_date_ticker_groups",
        note="groups the weekly diagnostic flagged as date+ticker duplicates",
    )
    out["weekly.canonical_headline_suggestions"] = _summarise_groups(
        weekly.get("canonical_headline_suggestions"),
        source="weekly.canonical_headline_suggestions",
        note="duplicate groups carrying a suggested_canonical_event_id pointer",
    )

    # Still Moving diagnostic -----------------------------------------------
    out["still_moving.missing_price_cache_cases"] = _summarise_list(
        still_moving.get("missing_price_cache_cases"),
        source="still_moving.missing_price_cache_cases",
        note="rows the still-moving diagnostic flagged as missing price_cache rows",
    )
    out["still_moving.bad_proxy_cases"] = _summarise_list(
        still_moving.get("bad_proxy_cases"),
        source="still_moving.bad_proxy_cases",
        note="rows whose primary_ticker is a broad-market or sector-broad ETF",
    )
    out["still_moving.no_persistence_cases"] = _summarise_list(
        still_moving.get("no_persistence_cases"),
        source="still_moving.no_persistence_cases",
        note="rows whose persistence_signal is null or Decaying",
    )
    out["still_moving.weak_ticker_cases"] = _summarise_list(
        still_moving.get("weak_ticker_cases"),
        source="still_moving.weak_ticker_cases",
        note="rows whose ticker_quality is missing_primary or no_cache",
    )

    # Combined diagnostic --------------------------------------------------
    out["combined.missing_mechanism_count"] = _summarise_list(
        combined.get("missing_mechanism_cases"),
        source="combined.missing_mechanism_cases",
        note="rows flagged with missing_mechanism_family across all Section C windows",
    )
    out["combined.bad_proxy_count"] = _summarise_list(
        combined.get("bad_proxy_cases"),
        source="combined.bad_proxy_cases",
        note="rows whose primary_ticker is a broad ETF across all windows",
    )
    out["combined.low_market_relevance_count"] = _summarise_low_relevance(
        combined,
        source="combined.low_market_relevance",
        note="rows whose market_relevance_score < 0.7 across all windows",
    )

    return out


def _summarise_list(
    rows: Any, *, source: str, note: str,
) -> dict[str, Any]:
    """Count rows and pull up to ``_SAMPLE_EVENT_LIMIT`` event_ids
    for the evidence sample."""
    samples: list[int] = []
    count = 0
    if isinstance(rows, list):
        count = len(rows)
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            ev_id = entry.get("event_id")
            if isinstance(ev_id, int) and ev_id not in samples:
                samples.append(ev_id)
                if len(samples) >= _SAMPLE_EVENT_LIMIT:
                    break
    return {
        "source_diagnostic": source,
        "evidence_count":    count,
        "sample_event_ids":  samples,
        "evidence_note":     note,
    }


def _summarise_groups(
    groups: Any, *, source: str, note: str,
) -> dict[str, Any]:
    """Count groups and pull up to ``_SAMPLE_EVENT_LIMIT`` event_ids
    from the first few groups for the evidence sample."""
    samples: list[int] = []
    count = 0
    if isinstance(groups, list):
        count = len(groups)
        for entry in groups:
            if not isinstance(entry, dict):
                continue
            ids = entry.get("event_ids")
            if isinstance(ids, list):
                for ev_id in ids:
                    if isinstance(ev_id, int) and ev_id not in samples:
                        samples.append(ev_id)
                        if len(samples) >= _SAMPLE_EVENT_LIMIT:
                            return {
                                "source_diagnostic": source,
                                "evidence_count":    count,
                                "sample_event_ids":  samples,
                                "evidence_note":     note,
                            }
    return {
        "source_diagnostic": source,
        "evidence_count":    count,
        "sample_event_ids":  samples,
        "evidence_note":     note,
    }


def _summarise_low_relevance(
    combined: dict[str, Any], *, source: str, note: str,
) -> dict[str, Any]:
    """Walk the combined diagnostic's per-section candidate lists
    and count entries carrying the low_market_relevance tag."""
    samples: list[int] = []
    count = 0
    for key in (
        "daily_candidates", "weekly_candidates",
        "still_moving_candidates",
    ):
        rows = combined.get(key) if isinstance(combined, dict) else None
        if not isinstance(rows, list):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            tags = entry.get("diagnostic_tags")
            if not isinstance(tags, list):
                continue
            if "low_market_relevance" not in tags:
                continue
            count += 1
            ev_id = entry.get("event_id")
            if isinstance(ev_id, int) and ev_id not in samples \
                    and len(samples) < _SAMPLE_EVENT_LIMIT:
                samples.append(ev_id)
    return {
        "source_diagnostic": source,
        "evidence_count":    count,
        "sample_event_ids":  samples,
        "evidence_note":     note,
    }


# ---------------------------------------------------------------------------
# Rule builder
# ---------------------------------------------------------------------------


def _build_rule_from_template(
    *,
    template:       dict[str, Any],
    evidence_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Materialise one rule template into the 8-field rule shape."""
    evidence_token = template["evidence_source"]
    evidence = evidence_index.get(evidence_token) or {
        "source_diagnostic": evidence_token,
        "evidence_count":    0,
        "sample_event_ids":  [],
        "evidence_note":     "no evidence available",
    }
    priority_pinned = template.get("priority_pinned")
    if priority_pinned in ("high", "medium", "low"):
        priority = priority_pinned
    else:
        priority = _priority_from_count(
            int(evidence.get("evidence_count") or 0),
        )

    return {
        "rule_id":                      template["rule_id"],
        "section":                      template["section"],
        "description":                  template["description"],
        "diagnostic_evidence":          dict(evidence),
        "expected_benefit":             template["expected_benefit"],
        "possible_false_positive_risk": template["possible_false_positive_risk"],
        "implementation_complexity":    template["implementation_complexity"],
        "priority":                     priority,
    }


def _priority_from_count(count: int) -> str:
    if count >= _PRIORITY_HIGH_THRESHOLD:
        return "high"
    if count >= _PRIORITY_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# evidence_from_diagnostics rollup
# ---------------------------------------------------------------------------


def _build_evidence_summary(
    *,
    payloads: dict[str, dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    """Per-input rollup so a downstream reader can confirm which
    diagnostics contributed and the headline counts."""
    out: dict[str, dict[str, Any]] = {}

    out["source_inventory"] = _summary_for_source_inventory(
        payloads.get("source_inventory"),
    )
    out["daily"] = _summary_for_daily(payloads.get("daily"))
    out["weekly"] = _summary_for_weekly(payloads.get("weekly"))
    out["still_moving"] = _summary_for_still_moving(
        payloads.get("still_moving"),
    )
    out["combined"] = _summary_for_combined(payloads.get("combined"))

    return out


def _summary_for_source_inventory(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        return {"present": False, "counts": {}}
    return {
        "present": True,
        "counts": {
            "daily_sources":          _safe_len(payload.get("daily_sources")),
            "weekly_sources":         _safe_len(payload.get("weekly_sources")),
            "still_moving_sources":   _safe_len(payload.get("still_moving_sources")),
            "suspected_quality_gaps": _safe_len(payload.get("suspected_quality_gaps")),
        },
    }


def _summary_for_daily(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        return {"present": False, "counts": {}}
    return {
        "present": True,
        "counts": {
            "candidates_checked":        _safe_int(payload.get("candidates_checked")),
            "accepted_like_candidates":  _safe_len(payload.get("accepted_like_candidates")),
            "junk_headlines":            _safe_len(payload.get("junk_headlines")),
            "raw_legal_text_cases":      _safe_len(payload.get("raw_legal_text_cases")),
            "off_topic_cases":           _safe_len(payload.get("off_topic_cases")),
            "vague_cases":               _safe_len(payload.get("vague_cases")),
            "duplicate_cases":           _safe_len(payload.get("duplicate_cases")),
            "missing_mechanism_cases":   _safe_len(payload.get("missing_mechanism_cases")),
        },
    }


def _summary_for_weekly(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        return {"present": False, "counts": {}}
    return {
        "present": True,
        "counts": {
            "candidates_checked":            _safe_int(payload.get("candidates_checked")),
            "duplicate_groups":              _safe_len(payload.get("duplicate_groups")),
            "repeated_date_ticker_groups":   _safe_len(payload.get("repeated_date_ticker_groups")),
            "repeated_headline_groups":      _safe_len(payload.get("repeated_headline_groups")),
            "mechanism_theme_candidates":    _safe_len(payload.get("mechanism_theme_candidates")),
            "canonical_headline_suggestions": _safe_len(payload.get("canonical_headline_suggestions")),
        },
    }


def _summary_for_still_moving(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        return {"present": False, "counts": {}}
    return {
        "present": True,
        "counts": {
            "candidates_checked":           _safe_int(payload.get("candidates_checked")),
            "defensible_candidates":        _safe_len(payload.get("defensible_candidates")),
            "weak_ticker_cases":            _safe_len(payload.get("weak_ticker_cases")),
            "bad_proxy_cases":              _safe_len(payload.get("bad_proxy_cases")),
            "missing_price_cache_cases":    _safe_len(payload.get("missing_price_cache_cases")),
            "no_persistence_cases":         _safe_len(payload.get("no_persistence_cases")),
            "duplicate_narrative_cases":    _safe_len(payload.get("duplicate_narrative_cases")),
        },
    }


def _summary_for_combined(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        return {"present": False, "counts": {}}
    return {
        "present": True,
        "counts": {
            "daily_candidates":         _safe_len(payload.get("daily_candidates")),
            "weekly_candidates":        _safe_len(payload.get("weekly_candidates")),
            "still_moving_candidates":  _safe_len(payload.get("still_moving_candidates")),
            "junk_headlines":           _safe_len(payload.get("junk_headlines")),
            "duplicate_groups":         _safe_len(payload.get("duplicate_groups")),
            "weak_ticker_cases":        _safe_len(payload.get("weak_ticker_cases")),
            "missing_mechanism_cases":  _safe_len(payload.get("missing_mechanism_cases")),
            "bad_proxy_cases":          _safe_len(payload.get("bad_proxy_cases")),
        },
    }


def _safe_len(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


# ---------------------------------------------------------------------------
# Output-file persistence
# ---------------------------------------------------------------------------


def _maybe_write_output(
    envelope: dict[str, Any], output_path: str,
) -> str | None:
    target = Path(output_path)
    if target.exists():
        return (
            f"refusing to overwrite existing path: {output_path}; "
            f"pick a new path or remove the file by hand before "
            f"re-running"
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
            fh.write("\n")
    except OSError as exc:
        return f"failed to write --output {output_path}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Section C filter rule proposal (proposal only — not applied)",
        "",
    ]
    lines.append(f"OK:                           {report['ok']}")
    lines.append(f"generated_at:                 {report['generated_at']}")
    lines.append("")
    lines.append("Rule counts:")
    lines.append(
        f"  daily_filter_proposals:        {len(report['daily_filter_proposals'])}"
    )
    lines.append(
        f"  weekly_filter_proposals:       {len(report['weekly_filter_proposals'])}"
    )
    lines.append(
        f"  still_moving_filter_proposals: "
        f"{len(report['still_moving_filter_proposals'])}"
    )
    lines.append(
        f"  cross_section_rules:           {len(report['cross_section_rules'])}"
    )
    lines.append(
        f"  highest_impact_rules:          {len(report['highest_impact_rules'])}"
    )
    lines.append(
        f"  rules_not_recommended_yet:     "
        f"{len(report['rules_not_recommended_yet'])}"
    )
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Section C filter rule proposal generator.  "
            "Reads the diagnostic JSON outputs and produces a "
            "concrete proposed filter plan.  Does not apply any "
            "filter, does not mutate any artifact.  No DB writes, "
            "no provider call, no LLM, no FastAPI."
        ),
    )
    parser.add_argument(
        "--json", dest="json_flag", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--source-inventory", dest="source_inventory_path",
        default=_DEFAULT_SOURCE_INVENTORY_PATH,
        help=(
            f"Path to section_c_source_inventory JSON "
            f"(default {_DEFAULT_SOURCE_INVENTORY_PATH}).  "
            f"Missing → warning, not error."
        ),
    )
    parser.add_argument(
        "--daily-diagnostic", dest="daily_diagnostic_path",
        default=_DEFAULT_DAILY_DIAGNOSTIC_PATH,
        help=(
            f"Path to section_c_daily_quality_diagnostic JSON "
            f"(default {_DEFAULT_DAILY_DIAGNOSTIC_PATH})."
        ),
    )
    parser.add_argument(
        "--weekly-diagnostic", dest="weekly_diagnostic_path",
        default=_DEFAULT_WEEKLY_DIAGNOSTIC_PATH,
        help=(
            f"Path to section_c_weekly_duplicate_diagnostic JSON "
            f"(default {_DEFAULT_WEEKLY_DIAGNOSTIC_PATH})."
        ),
    )
    parser.add_argument(
        "--still-moving-diagnostic", dest="still_moving_diagnostic_path",
        default=_DEFAULT_STILL_MOVING_DIAGNOSTIC_PATH,
        help=(
            f"Path to section_c_still_moving_quality_diagnostic JSON "
            f"(default {_DEFAULT_STILL_MOVING_DIAGNOSTIC_PATH})."
        ),
    )
    parser.add_argument(
        "--combined-diagnostic", dest="combined_diagnostic_path",
        default=_DEFAULT_COMBINED_DIAGNOSTIC_PATH,
        help=(
            f"Path to section_c_quality_diagnostic JSON "
            f"(default {_DEFAULT_COMBINED_DIAGNOSTIC_PATH})."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to persist the proposal JSON.  Refuses "
            "to overwrite an existing path.  When omitted, the "
            "script has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_section_c_filter_rule_proposal(
        source_inventory_path=args.source_inventory_path,
        daily_diagnostic_path=args.daily_diagnostic_path,
        weekly_diagnostic_path=args.weekly_diagnostic_path,
        still_moving_diagnostic_path=args.still_moving_diagnostic_path,
        combined_diagnostic_path=args.combined_diagnostic_path,
        output_path=args.output_path,
    )
    if args.json_flag:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_section_c_filter_rule_proposal",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

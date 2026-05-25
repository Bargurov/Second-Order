#!/usr/bin/env python3
"""Daily artifact-gate implementation plan.

A read-only planner that turns the upstream gate-design — from
:mod:`scripts.section_c_daily_artifact_gate_plan` — into a concrete
implementation plan an operator could follow later.  Where the
upstream planner describes the gate's identity, this planner names
the exact production files an implementer would inspect, the data
contract those files would adopt, the migration sequence, and the
tests an implementer would add along the way.

The plan exists because Daily currently lacks ``mechanism_family`` in
``news_inbox.json``.  The Daily mechanism-enrichment diagnostic
recommends the artifact-gate path — Section C would refuse to promote
an inbox row unless an operator-reviewed analyzed-event artifact
carries the four spec-pinned fields (``mechanism_family``,
``primary_ticker``, ``benchmark_ticker``, ``market_relevance``).  This
planner takes that recommendation and turns it into an
implementation-ready punch list, without writing or running any of
the change itself.

Read-only by construction
-------------------------

* The planner emits a stable design.  It does not read the events
  DB, the inbox, or any artifact file at runtime; the design is the
  output.
* No DB writes anywhere.  No ``yfinance``, ``market_data``, LLM, or
  paid provider call.  No FastAPI surface (never imports ``api`` or
  ``routes.*``).
* No mutation of ``news_inbox``, ``events``, ``curated_candidates``,
  or any artifact file.  ``--output`` writes a single JSON file
  only when explicitly passed.
* No production filter is changed.  ``target_files`` names which
  files the operator would touch in a follow-up worksheet; the
  planner itself only describes them.
* No new ``mechanism_family`` value is assigned anywhere.  The plan
  describes where that value would come from (an
  operator-reviewed artifact); it does not produce one.
* Fuzzy / LLM-based headline matching is rejected by construction
  in ``proposed_filter_behavior.fuzzy_matching_default``, regardless
  of the diagnostic's current state.

Conservative wording
--------------------

Banned tokens in emitted prose: ``proof``, ``proven``, ``broken``,
``wrong``, ``must fix``, ``guaranteed``, ``automatically``,
``definitely``, ``causes``, ``causation``, ``will assign``,
``will enrich``, ``correct mechanism``, ``rule guarantees``,
``alpha generated``, ``correct ticker``.  The planner says "would"
and "could" — never "will".

Output contract (JSON)::

    {
      "ok":                              bool,
      "target_files":                    [ {path, role, change_summary}, ... ],
      "proposed_data_contract": {
        "artifact_kind":     str,
        "required_fields":   [ {name, type, source, rationale}, ... ],
        "link_field":        {name, type, rationale},
        "storage_location":  str,
      },
      "proposed_filter_behavior": {
        "where":                            str,
        "when":                             str,
        "behavior_on_complete_artifact":    str,
        "behavior_on_missing_artifact":     str,
        "behavior_on_incomplete_artifact":  str,
        "fuzzy_matching_default":           str,
      },
      "allowed_daily_candidate_shape": {
        "inbox_row":         dict,
        "artifact":          dict,
        "promotion_outcome": "admitted",
        "rationale":         str,
      },
      "blocked_daily_candidate_shape": {
        "inbox_row":         dict,
        "artifact":          dict | None,
        "missing_fields":    [str, ...],
        "promotion_outcome": "held_for_review",
        "rationale":         str,
      },
      "migration_steps": [
        {step, title, description, files, verification},
        ...
      ],
      "tests_to_add": [
        {test_id, scope, description, asserts},
        ...
      ],
      "false_positive_risks":   [str, ...],
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

Usage::

    python scripts/daily_artifact_gate_implementation_plan.py --json
    python scripts/daily_artifact_gate_implementation_plan.py --json \\
        --output artifacts/daily_artifact_gate_implementation_plan.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Target files — the exact production files an implementer would
# inspect or edit later.  The planner names each path and a concrete
# responsibility; it does NOT propose code or touch the file.
# ---------------------------------------------------------------------------


_TARGET_FILES: tuple[dict[str, str], ...] = (
    {
        "path": "news_fetch.py",
        "role": "inbox loader",
        "change_summary": (
            "An inbox-loader extension would attach a stable "
            "candidate_id to each loaded row.  The planner does not "
            "propose an allocation scheme; the operator decides "
            "whether the id is a hash of (source, url, published_at) "
            "or an operator-assigned key.  No filter logic lives "
            "here — the loader only tags rows."
        ),
    },
    {
        "path": "news_inbox.json",
        "role": "operator-visible inbox file",
        "change_summary": (
            "The inbox schema would gain a candidate_id field so the "
            "gate can look up the matching artifact deterministically.  "
            "No mechanism_family field is proposed on the inbox row "
            "itself; the gate would read mechanism_family from the "
            "artifact, not from the inbox."
        ),
    },
    {
        "path": "routes/movers.py",
        "role": "Daily Section C promotion boundary (filter host)",
        "change_summary": (
            "The Daily branch of the movers route would gate "
            "promotion behind the artifact's existence and the "
            "artifact's four required fields.  Rows whose artifact "
            "is missing or incomplete would be hidden from the "
            "Section C panel and surfaced on the operator review "
            "worklist instead.  The planner names the file as the "
            "location of the gate and does not edit it."
        ),
    },
    {
        "path": "scripts/manual_event_intake_worksheet.py",
        "role": "analyzed-event artifact emitter",
        "change_summary": (
            "An emission mode that writes one analyzed_event_artifact "
            "JSON per filled worksheet row would feed the gate "
            "without a separate operator surface.  The worksheet "
            "already carries the four required fields plus a "
            "candidate_id column."
        ),
    },
    {
        "path": "artifacts/",
        "role": "artifact storage directory",
        "change_summary": (
            "The gate would read analyzed_event_artifact files from "
            "a subdirectory under artifacts/ keyed by candidate_id.  "
            "A freshness window on each artifact would let the "
            "operator see a stale gate as a stale row rather than "
            "as a silently-dropped one."
        ),
    },
    {
        "path": "scripts/section_c_daily_quality_diagnostic.py",
        "role": "diagnostic surface (read-only)",
        "change_summary": (
            "The existing diagnostic would gain an artifact_present "
            "/ artifact_fields_complete column per inbox row so the "
            "operator could read, at a glance, which rows the gate "
            "would admit and which it would hold for review.  "
            "Descriptive only — the diagnostic does not enforce the "
            "gate."
        ),
    },
)


# ---------------------------------------------------------------------------
# Data contract — the four spec-pinned required fields, in spec
# order, plus the link field (candidate_id).  Each field carries an
# explicit ``source`` describing where the value would come from.
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS: tuple[dict[str, str], ...] = (
    {
        "name": "mechanism_family",
        "type": "string (non-empty, not 'none')",
        "source": (
            "operator-reviewed analyzed-event artifact emitted by "
            "scripts/manual_event_intake_worksheet.py (or another "
            "operator-curated source such as the curated-event "
            "YAML).  The inbox row itself does not carry "
            "mechanism_family; the gate reads it from the artifact."
        ),
        "rationale": (
            "Section C is mechanism-keyed by construction; without "
            "a mechanism label the surface cannot describe why the "
            "row belongs there.  The Daily mechanism-enrichment "
            "diagnostic already reports the inbox carries no "
            "mechanism_family today."
        ),
    },
    {
        "name": "primary_ticker",
        "type": "string (non-empty, uppercase)",
        "source": (
            "operator-reviewed artifact field; pulled from the "
            "worksheet's primary_ticker column (or the curated YAML "
            "entry's id-mapped primary_ticker)."
        ),
        "rationale": (
            "The Section C row needs a single-name ticker so the "
            "downstream Still Moving check can reason about price "
            "behaviour; the inbox row carries no ticker today."
        ),
    },
    {
        "name": "benchmark_ticker",
        "type": "string (non-empty, uppercase)",
        "source": (
            "operator-reviewed artifact field; pulled from the "
            "worksheet's benchmark_ticker column or the curated "
            "YAML entry's benchmark_ticker."
        ),
        "rationale": (
            "Benchmark-adjusted evidence is the contract the Still "
            "Moving diagnostic enforces; admitting a Section C row "
            "without a benchmark would leave the downstream check "
            "with no comparator."
        ),
    },
    {
        "name": "market_relevance",
        "type": "float in [0.0, 1.0] (operator-supplied)",
        "source": (
            "operator-supplied artifact field; the operator records "
            "an explicit relevance score on the worksheet row, "
            "replacing the inbox's coarse keyword-derived score."
        ),
        "rationale": (
            "An explicit operator-supplied relevance score replaces "
            "the inbox's coarse keyword-derived score, which the "
            "Daily quality diagnostic flagged as too noisy on its "
            "own; the operator's score is the audit trail."
        ),
    },
)


_LINK_FIELD: dict[str, str] = {
    "name": "candidate_id",
    "type": "string (stable across regenerations)",
    "rationale": (
        "A stable candidate_id on each inbox row and on the matching "
        "artifact lets the gate look up the artifact by id rather "
        "than by headline string.  The planner does not propose an "
        "allocation scheme here; the operator decides whether the "
        "id is a hash of (source, url, published_at) or an "
        "operator-assigned key."
    ),
}


_REQUIRED_FIELD_NAMES: tuple[str, ...] = tuple(
    f["name"] for f in _REQUIRED_FIELDS
)


# ---------------------------------------------------------------------------
# Proposed filter behavior — the gate as the implementer would wire
# it.  Every behavior_on_* string says what would happen to a Daily
# candidate in that state.
# ---------------------------------------------------------------------------


_FILTER_BEHAVIOR: dict[str, str] = {
    "where": (
        "Daily branch of routes/movers.py — the Section C "
        "promotion boundary that admits an inbox row into the live "
        "Daily view.  The filter is co-located with the existing "
        "Section C selection logic, not at the inbox loader."
    ),
    "when": (
        "At the Section C promotion boundary, not at ingestion.  "
        "The inbox loader continues to write rows; the gate only "
        "governs which of those rows surface in Section C.  This "
        "keeps ingestion lossless and makes the held-for-review "
        "population observable on the operator worklist."
    ),
    "behavior_on_complete_artifact": (
        "The row would be admitted to Section C.  Admission "
        "criteria: the inbox row carries a stable candidate_id, an "
        "analyzed_event_artifact keyed by that id exists on disk "
        "under artifacts/, the artifact carries non-empty values "
        "for all four required fields, and the artifact's review "
        "timestamp is inside the operator-configured freshness "
        "window."
    ),
    "behavior_on_missing_artifact": (
        "No analyzed_event_artifact exists for the row.  The gate "
        "would hold the row for review — it would not surface in "
        "Section C and would appear on the operator review "
        "worklist instead.  The operator could then either fill an "
        "artifact (if the row describes a real event) or drop the "
        "row (if it is a generic wrap).  The limitation is held in "
        "view, not hidden."
    ),
    "behavior_on_incomplete_artifact": (
        "An analyzed_event_artifact exists but is missing one or "
        "more of the four required fields.  The row would also be "
        "held for review (not surfaced in Section C) and the "
        "missing fields would be listed on the operator worklist "
        "so the operator could complete the artifact rather than "
        "re-discover the gap."
    ),
    "fuzzy_matching_default": (
        "Fuzzy or LLM-based headline matching is rejected as the "
        "gate's default source.  A mechanism_family attached to a "
        "headline by an unconfirmed fuzzy match would look "
        "confident but would not be auditable; the gate insists on "
        "a reviewed artifact instead.  An operator could later "
        "evaluate an LLM-assisted pre-fill step behind explicit "
        "operator review, but that path is not the default."
    ),
}


# ---------------------------------------------------------------------------
# Worked candidate shapes — illustrative shapes pinned to the gate's
# two outcomes.  Not derived from live inbox state.
# ---------------------------------------------------------------------------


_ALLOWED_SHAPE: dict[str, Any] = {
    "inbox_row": {
        "candidate_id": "20260512_opec_supply_cut_001",
        "headline": (
            "OPEC members agree to extend voluntary oil output cuts "
            "through next quarter"
        ),
        "published_at": "2026-05-12T08:15:00Z",
        "source": "operator_demo_fixture",
    },
    "artifact": {
        "candidate_id":     "20260512_opec_supply_cut_001",
        "mechanism_family": "supply_shock",
        "primary_ticker":   "XOM",
        "benchmark_ticker": "XLE",
        "market_relevance": 0.85,
        "review_signed_by": "operator",
    },
    "promotion_outcome": "admitted",
    "rationale": (
        "Inbox row carries a stable candidate_id; an "
        "analyzed_event_artifact under artifacts/ keyed by that "
        "candidate_id exists and carries non-empty values for every "
        "required field on a reviewed artifact.  The gate would "
        "admit the row into Section C."
    ),
}


_BLOCKED_SHAPE: dict[str, Any] = {
    "inbox_row": {
        "candidate_id": "20260512_market_wrap_007",
        "headline": (
            "Market wrap: stocks edge higher on quiet trading day"
        ),
        "published_at": "2026-05-12T20:05:00Z",
        "source": "operator_demo_fixture",
    },
    "artifact": None,
    "missing_fields": list(_REQUIRED_FIELD_NAMES),
    "promotion_outcome": "held_for_review",
    "rationale": (
        "No analyzed_event_artifact exists for the row.  The "
        "headline is a generic market-wrap phrase the Daily quality "
        "diagnostic already classifies as vague.  The gate would "
        "hold the row for review — Section C would not show it; "
        "the operator review worklist would.  The operator could "
        "then either fill an artifact (if the row describes a real "
        "event) or drop the row.  The limitation is surfaced, not "
        "hidden."
    ),
}


# ---------------------------------------------------------------------------
# Migration steps — an ordered sequence the implementer would follow.
# The candidate_id tagging and artifact emitter steps land BEFORE the
# gate-wiring step so the gate has both a link key and an input
# source before it filters.
# ---------------------------------------------------------------------------


_MIGRATION_STEPS: tuple[dict[str, Any], ...] = (
    {
        "step": 1,
        "title": "Tag inbox rows with a stable candidate_id",
        "description": (
            "Extend the inbox loader to attach a stable candidate_id "
            "field to each row written to news_inbox.json.  The "
            "allocation scheme is an operator decision (hash of "
            "(source, url, published_at) is a reasonable starting "
            "point).  No filter logic lives here.  The aim is that "
            "every inbox row carries a deterministic key the gate "
            "can look up later."
        ),
        "files": ["news_fetch.py", "news_inbox.json"],
        "verification": (
            "Every row in news_inbox.json carries a non-empty "
            "candidate_id; a regenerator run produces the same id "
            "for the same (source, url, published_at) input."
        ),
    },
    {
        "step": 2,
        "title": (
            "Emit analyzed_event_artifact files from the manual "
            "worksheet"
        ),
        "description": (
            "Add an emission mode to "
            "scripts/manual_event_intake_worksheet.py that writes "
            "one analyzed_event_artifact JSON per filled worksheet "
            "row under artifacts/.  Each artifact would carry the "
            "candidate_id from the worksheet row, the four required "
            "fields, and an operator review signature.  The "
            "operator owns the row content; the emitter only "
            "serialises it."
        ),
        "files": [
            "scripts/manual_event_intake_worksheet.py",
            "artifacts/",
        ],
        "verification": (
            "Filling a worksheet row and re-running the worksheet "
            "in emit mode produces an artifact file under "
            "artifacts/<candidate_id>.json that carries the four "
            "required fields and a review_signed_by field."
        ),
    },
    {
        "step": 3,
        "title": (
            "Surface artifact presence on the read-only quality "
            "diagnostic"
        ),
        "description": (
            "Extend "
            "scripts/section_c_daily_quality_diagnostic.py to "
            "report, per inbox row, whether an artifact exists and "
            "whether every required field is present.  This is a "
            "descriptive surface — the diagnostic does not gate "
            "anything.  It gives the operator a preview of how the "
            "gate would behave before the gate is wired."
        ),
        "files": [
            "scripts/section_c_daily_quality_diagnostic.py",
        ],
        "verification": (
            "The diagnostic JSON envelope gains an "
            "artifact_present_count and missing_fields_breakdown "
            "block per Daily candidate; running the diagnostic "
            "before the gate is wired produces a non-empty "
            "missing-fields breakdown today."
        ),
    },
    {
        "step": 4,
        "title": (
            "Wire the Section C gate in the Daily movers route, "
            "behind a feature flag"
        ),
        "description": (
            "Add the artifact-presence-and-completeness check to "
            "the Daily branch of routes/movers.py at the Section C "
            "promotion boundary.  Behind an operator-visible "
            "feature flag so the rollback path is obvious and the "
            "empty-Section-C case is a surfaced limitation rather "
            "than a silent regression.  Rows that fail the check "
            "would not surface in Section C; they would appear on "
            "the operator review worklist."
        ),
        "files": ["routes/movers.py"],
        "verification": (
            "With the flag off, Section C behavior is unchanged "
            "from today.  With the flag on, an inbox row whose "
            "artifact is missing or incomplete does not surface in "
            "the Section C JSON response; the same row surfaces on "
            "the operator review worklist."
        ),
    },
    {
        "step": 5,
        "title": (
            "Add operator review worklist for held rows"
        ),
        "description": (
            "Surface the held-for-review population as an explicit "
            "operator worklist so a held row is observable, not "
            "silently dropped.  The worklist entry would carry the "
            "inbox candidate_id, the headline, and the list of "
            "missing fields the operator could fill on the "
            "worksheet to admit the row."
        ),
        "files": [
            "scripts/section_c_daily_quality_diagnostic.py",
        ],
        "verification": (
            "The diagnostic emits a held_for_review array; each "
            "entry has a candidate_id, a headline, and a "
            "missing_fields list that matches the gate's view of "
            "the row."
        ),
    },
)


# ---------------------------------------------------------------------------
# Tests to add — the assertions the implementer would write as the
# gate lands.  Each entry names a scope and a non-empty asserts list;
# the planner does not write production tests, only describes them.
# ---------------------------------------------------------------------------


_TESTS_TO_ADD: tuple[dict[str, Any], ...] = (
    {
        "test_id": "inbox_loader_emits_stable_candidate_id",
        "scope": "news_fetch.py inbox loader unit test",
        "description": (
            "Pin that the inbox loader attaches a stable, "
            "non-empty candidate_id to every row written to "
            "news_inbox.json, and that the id is deterministic "
            "across reruns for the same (source, url, "
            "published_at) input."
        ),
        "asserts": [
            "every row in the rendered inbox has a candidate_id "
            "key with a non-empty string value",
            "feeding the same (source, url, published_at) tuple "
            "twice produces the same candidate_id",
            "two distinct rows with different urls produce "
            "different candidate_ids",
        ],
    },
    {
        "test_id": "manual_worksheet_emits_artifact_with_required_fields",
        "scope": (
            "scripts/manual_event_intake_worksheet.py emit-mode "
            "integration test"
        ),
        "description": (
            "Pin that the worksheet emitter writes one artifact "
            "JSON per filled row, that the artifact carries the "
            "four required fields and the link candidate_id, and "
            "that an empty row does not emit an artifact."
        ),
        "asserts": [
            "a filled worksheet row produces an artifact file "
            "under artifacts/<candidate_id>.json",
            "the artifact JSON has non-empty values for "
            "mechanism_family, primary_ticker, benchmark_ticker, "
            "and market_relevance",
            "an empty / partially-filled worksheet row does not "
            "emit an artifact file",
        ],
    },
    {
        "test_id": "movers_route_section_c_admits_only_complete_artifacts",
        "scope": (
            "routes/movers.py Daily Section C integration test "
            "(behind feature flag)"
        ),
        "description": (
            "Pin that with the gate flag on, the Section C JSON "
            "response carries only rows whose artifact exists and "
            "carries every required field, and that rows whose "
            "artifact is missing or incomplete do not surface in "
            "Section C."
        ),
        "asserts": [
            "with flag off, response is byte-for-byte identical "
            "to today's behavior",
            "with flag on and an inbox row carrying a complete "
            "artifact, the row appears in the Section C response",
            "with flag on and an inbox row whose artifact is "
            "missing, the row does not appear in the Section C "
            "response",
            "with flag on and an inbox row whose artifact is "
            "incomplete (one required field empty), the row does "
            "not appear in the Section C response",
        ],
    },
    {
        "test_id": "diagnostic_surfaces_held_for_review_breakdown",
        "scope": (
            "scripts/section_c_daily_quality_diagnostic.py "
            "diagnostic envelope test"
        ),
        "description": (
            "Pin that the diagnostic surfaces a held_for_review "
            "array and a missing_fields breakdown per held row, so "
            "the operator can see the limitation in view rather "
            "than as a silently-dropped row."
        ),
        "asserts": [
            "the diagnostic envelope has a held_for_review key "
            "carrying a list of entries",
            "each held_for_review entry has candidate_id, "
            "headline, and missing_fields fields",
            "the count of held rows matches the count of inbox "
            "rows that lack a complete artifact in the fixture",
        ],
    },
    {
        "test_id": "gate_rejects_fuzzy_default",
        "scope": "design / configuration invariant test",
        "description": (
            "Pin that the gate's default source list does not "
            "include a fuzzy / LLM headline matcher, so a future "
            "refactor cannot silently flip the default to "
            "unconfirmed matching."
        ),
        "asserts": [
            "the gate's allowed source list does not include "
            "'fuzzy_headline_matching' as a default",
            "the gate's rejected source list includes "
            "'fuzzy_headline_matching' with an auditability "
            "rationale",
        ],
    },
)


# ---------------------------------------------------------------------------
# False-positive risks — short bullets the implementer should weigh.
# ---------------------------------------------------------------------------


_FP_RISKS: tuple[str, ...] = (
    "an operator backlog in artifact production would hold real "
    "news off the Section C surface; the gate should pair with a "
    "freshness window so stale-or-missing artifacts surface as a "
    "stale row rather than as a silently-dropped one.",
    "a candidate_id collision (two inbox rows hashing to the same "
    "id) would attach one artifact to two rows; the implementer "
    "should pick an allocation scheme that is stable across "
    "regenerations but unique per row before any production "
    "change.",
    "an artifact carrying a stale benchmark_ticker (e.g. the "
    "benchmark changed sector category) could surface a row whose "
    "Still Moving check then degrades; an artifact-level review "
    "timestamp would let the operator spot stale benchmark "
    "choices during audit.",
    "an over-restrictive gate during early roll-out could starve "
    "Section C; the feature-flag staging in step 4 lets the "
    "operator roll the gate back without redeploy, and the "
    "empty-Section-C case is then a surfaced limitation rather "
    "than a silent regression.",
    "a candidate source that ships mechanism_family without an "
    "operator signature would re-introduce the audit gap the gate "
    "exists to close; every artifact source in the plan carries an "
    "operator review step by construction.",
)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_daily_artifact_gate_implementation_plan(
    *,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Build the Daily artifact-gate implementation plan.

    See module docstring for the full output contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    proposed_data_contract: dict[str, Any] = {
        "artifact_kind": (
            "analyzed_event_artifact (one JSON file per Daily "
            "candidate, keyed by candidate_id, written by the "
            "operator-driven manual_event_intake_worksheet emitter "
            "or an equivalent operator-reviewed source)."
        ),
        "required_fields": [dict(f) for f in _REQUIRED_FIELDS],
        "link_field":      dict(_LINK_FIELD),
        "storage_location": (
            "artifacts/ subdirectory keyed by candidate_id (e.g. "
            "artifacts/<candidate_id>.json).  The gate would read "
            "files from this location; no other location is "
            "proposed."
        ),
    }

    envelope: dict[str, Any] = {
        "ok": not errors,
        "target_files": [dict(t) for t in _TARGET_FILES],
        "proposed_data_contract": proposed_data_contract,
        "proposed_filter_behavior": dict(_FILTER_BEHAVIOR),
        "allowed_daily_candidate_shape": {
            "inbox_row":         dict(_ALLOWED_SHAPE["inbox_row"]),
            "artifact":          dict(_ALLOWED_SHAPE["artifact"]),
            "promotion_outcome": _ALLOWED_SHAPE["promotion_outcome"],
            "rationale":         _ALLOWED_SHAPE["rationale"],
        },
        "blocked_daily_candidate_shape": {
            "inbox_row":         dict(_BLOCKED_SHAPE["inbox_row"]),
            "artifact":          _BLOCKED_SHAPE["artifact"],
            "missing_fields":    list(_BLOCKED_SHAPE["missing_fields"]),
            "promotion_outcome": _BLOCKED_SHAPE["promotion_outcome"],
            "rationale":         _BLOCKED_SHAPE["rationale"],
        },
        "migration_steps": [
            {
                "step":         s["step"],
                "title":        s["title"],
                "description":  s["description"],
                "files":        list(s["files"]),
                "verification": s["verification"],
            }
            for s in _MIGRATION_STEPS
        ],
        "tests_to_add": [
            {
                "test_id":     t["test_id"],
                "scope":       t["scope"],
                "description": t["description"],
                "asserts":     list(t["asserts"]),
            }
            for t in _TESTS_TO_ADD
        ],
        "false_positive_risks": list(_FP_RISKS),
        "warnings":             warnings,
        "errors":               errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Daily artifact-gate implementation plan", "",
    ]
    lines.append(f"OK: {report['ok']}")
    lines.append("")
    lines.append(f"Target files ({len(report['target_files'])}):")
    for t in report["target_files"]:
        lines.append(
            f"  - {t.get('path')!s:<48} {t.get('role')}"
        )
        lines.append(f"      {t.get('change_summary')}")
    lines.append("")
    contract = report["proposed_data_contract"]
    lines.append("Proposed data contract:")
    lines.append(f"  artifact_kind:    {contract.get('artifact_kind')}")
    lines.append(f"  storage_location: {contract.get('storage_location')}")
    lines.append(f"  required fields ({len(contract['required_fields'])}):")
    for f in contract["required_fields"]:
        lines.append(f"    - {f.get('name')!s:<20} {f.get('type')}")
        lines.append(f"        source:    {f.get('source')}")
        lines.append(f"        rationale: {f.get('rationale')}")
    link = contract.get("link_field") or {}
    lines.append(
        f"  link field: {link.get('name')} ({link.get('type')})"
    )
    lines.append(f"      rationale: {link.get('rationale')}")
    lines.append("")
    behavior = report["proposed_filter_behavior"]
    lines.append("Proposed filter behavior:")
    for k in (
        "where",
        "when",
        "behavior_on_complete_artifact",
        "behavior_on_missing_artifact",
        "behavior_on_incomplete_artifact",
        "fuzzy_matching_default",
    ):
        lines.append(f"  {k}:")
        lines.append(f"      {behavior.get(k)}")
    lines.append("")
    allowed = report["allowed_daily_candidate_shape"]
    lines.append("Allowed Daily candidate shape:")
    lines.append(
        f"  inbox candidate_id: {allowed['inbox_row'].get('candidate_id')}"
    )
    lines.append(f"  outcome:            {allowed.get('promotion_outcome')}")
    lines.append("")
    blocked = report["blocked_daily_candidate_shape"]
    lines.append("Blocked Daily candidate shape:")
    lines.append(
        f"  inbox candidate_id: {blocked['inbox_row'].get('candidate_id')}"
    )
    lines.append(f"  outcome:            {blocked.get('promotion_outcome')}")
    lines.append(
        f"  missing fields:     {', '.join(blocked.get('missing_fields', []))}"
    )
    lines.append("")
    lines.append(f"Migration steps ({len(report['migration_steps'])}):")
    for s in report["migration_steps"]:
        lines.append(f"  {s.get('step')}. {s.get('title')}")
        lines.append(f"      files: {', '.join(s.get('files', []))}")
        lines.append(f"      verify: {s.get('verification')}")
    lines.append("")
    lines.append(f"Tests to add ({len(report['tests_to_add'])}):")
    for t in report["tests_to_add"]:
        lines.append(f"  - {t.get('test_id')}")
        lines.append(f"      scope:       {t.get('scope')}")
        lines.append(f"      description: {t.get('description')}")
    lines.append("")
    lines.append(
        f"False-positive risks ({len(report['false_positive_risks'])}):"
    )
    for risk in report["false_positive_risks"]:
        lines.append(f"  - {risk}")
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


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Daily artifact-gate implementation plan.  "
            "Turns the artifact-gated inclusion design from "
            "scripts/section_c_daily_artifact_gate_plan.py into a "
            "concrete implementation punch list (target files, data "
            "contract, migration steps, tests to add).  Does NOT "
            "mutate news_inbox, events, curated_candidates, or any "
            "artifact.  Does NOT assign mechanism_family.  Does NOT "
            "recommend fuzzy / LLM matching as a default."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text plan.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the planner has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_daily_artifact_gate_implementation_plan(
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_daily_artifact_gate_implementation_plan",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

"""Tests for ``scripts/section_c_daily_mechanism_enrichment_plan.py``.

The planner is a read-only follow-up to the Daily mechanism-
enrichment diagnostic.  It proposes which forward path could
attach a ``mechanism_family`` value to a Daily candidate BEFORE the
candidate enters Section C, given the diagnostic's current finding
that ``news_inbox.json`` carries no ``mechanism_family`` and the
live events DB has no reliable enrichment source.

Pin the contract:

* Read-only.  No DB writes; no ``yfinance``, ``market_data``,
  LLM, or paid provider call; no FastAPI surface.
* Output dict has EXACTLY these 10 keys::

    ok, candidates_checked, enrichment_source_status,
    feasible_paths, infeasible_paths, recommended_path,
    required_schema_changes, false_positive_risks,
    warnings, errors

* The planner ALWAYS lists three forward-looking paths as
  feasible: enrich-at-ingestion, artifact-gate, manual review
  queue.
* The planner ALWAYS lists ``fuzzy_llm_matching`` in
  ``infeasible_paths`` — the spec forbids it as a default.
* The exact / normalised match path lands in ``infeasible_paths``
  when no enrichment source has rows OR when the diagnostic
  surfaced no matches OR when there were gaps remaining.
* The recommended path is
  ``require_analyzed_event_artifact_before_section_c_inclusion``
  unless the catalogue is pruned — pinned so a future drift gets
  caught.
* Conservative wording: no banned tokens in the rendered output.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import (  # noqa: E402
    section_c_daily_mechanism_enrichment_plan as cli,
)


_REQUIRED_TOP_KEYS = (
    "ok",
    "candidates_checked",
    "enrichment_source_status",
    "feasible_paths",
    "infeasible_paths",
    "recommended_path",
    "required_schema_changes",
    "false_positive_risks",
    "warnings",
    "errors",
)


_FEASIBLE_KEYS = (
    "path_id",
    "description",
    "trigger_conditions",
)


_INFEASIBLE_KEYS = (
    "path_id",
    "description",
    "reason_infeasible",
)


_SCHEMA_KEYS = (
    "surface",
    "field_or_file",
    "rationale",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "broken",
    "wrong",
    "must fix",
    "guaranteed",
    "automatically",
    "definitely",
    "causes",
    "causation",
    "will assign",
    "will enrich",
    "correct mechanism",
    "rule guarantees",
)


_PATH_EXACT_MATCH          = "exact_or_normalized_event_match"
_PATH_INGESTION_ALLOW_LIST = "enrich_at_ingestion_via_curated_allow_list"
_PATH_ARTIFACT_GATE        = (
    "require_analyzed_event_artifact_before_section_c_inclusion"
)
_PATH_MANUAL_REVIEW_QUEUE  = "manual_operator_review_queue"
_PATH_FUZZY_LLM            = "fuzzy_llm_matching"


# ---------------------------------------------------------------------------
# Synthetic diagnostic payloads
# ---------------------------------------------------------------------------


def _diagnostic_payload(
    *,
    candidates_checked:   int = 0,
    sources:              list[dict[str, Any]] | None = None,
    possible_matches:     list[dict[str, Any]] | None = None,
    enrichment_gaps:      list[dict[str, Any]] | None = None,
    warnings:             list[str] | None = None,
    errors:               list[str] | None = None,
) -> dict[str, Any]:
    if sources is None:
        sources = [
            {"source": "events.mechanism_family",
             "present": False, "rows_with_value": 0},
            {"source": "curated_candidates.mechanism_family",
             "present": False, "rows_with_value": 0},
        ]
    return {
        "ok":                                   not (errors or []),
        "daily_candidates_checked":             candidates_checked,
        "candidates_without_mechanism_family":  candidates_checked,
        "possible_event_matches":               possible_matches or [],
        "enrichment_sources_available":         sources,
        "enrichment_gaps":                      enrichment_gaps or [],
        "recommended_enrichment_path":          "stub recommendation",
        "warnings":                             warnings or [],
        "errors":                               errors or [],
    }


def _patch_diagnostic(payload: dict[str, Any]):
    return patch.object(
        cli, "_build_enrichment_diagnostic",
        return_value=payload,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_empty_diagnostic(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertTrue(report["ok"])
        self.assertEqual(report["candidates_checked"], 0)
        self.assertEqual(report["errors"], [])

    def test_feasible_path_entries_have_required_fields(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        for p in report["feasible_paths"]:
            self.assertEqual(set(p.keys()), set(_FEASIBLE_KEYS))
            self.assertIsInstance(p["trigger_conditions"], list)
            self.assertGreater(len(p["trigger_conditions"]), 0)

    def test_infeasible_path_entries_have_required_fields(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        for p in report["infeasible_paths"]:
            self.assertEqual(set(p.keys()), set(_INFEASIBLE_KEYS))
            self.assertIsInstance(p["reason_infeasible"], str)
            self.assertGreater(len(p["reason_infeasible"]), 0)

    def test_schema_change_entries_have_required_fields(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        for c in report["required_schema_changes"]:
            self.assertEqual(set(c.keys()), set(_SCHEMA_KEYS))


# ---------------------------------------------------------------------------
# Path-catalogue invariants
# ---------------------------------------------------------------------------


class TestPathCatalogue(unittest.TestCase):
    def test_three_forward_paths_always_feasible(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        feasible_ids = {p["path_id"] for p in report["feasible_paths"]}
        self.assertIn(_PATH_INGESTION_ALLOW_LIST, feasible_ids)
        self.assertIn(_PATH_ARTIFACT_GATE, feasible_ids)
        self.assertIn(_PATH_MANUAL_REVIEW_QUEUE, feasible_ids)

    def test_fuzzy_llm_always_infeasible(self) -> None:
        # With no enrichment sources.
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        ids = {p["path_id"] for p in report["infeasible_paths"]}
        self.assertIn(_PATH_FUZZY_LLM, ids)

        # With full enrichment sources and every candidate matching.
        payload = _diagnostic_payload(
            candidates_checked=2,
            sources=[
                {"source": "events.mechanism_family",
                 "present": True, "rows_with_value": 5},
                {"source": "curated_candidates.mechanism_family",
                 "present": False, "rows_with_value": 0},
            ],
            possible_matches=[
                {"inbox_headline": "A", "match_type": "exact"},
                {"inbox_headline": "B", "match_type": "normalized"},
            ],
            enrichment_gaps=[],
        )
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        ids = {p["path_id"] for p in report["infeasible_paths"]}
        self.assertIn(_PATH_FUZZY_LLM, ids,
                      "fuzzy_llm_matching must always be infeasible")


# ---------------------------------------------------------------------------
# Exact / normalised match feasibility
# ---------------------------------------------------------------------------


class TestExactMatchFeasibility(unittest.TestCase):
    def test_no_sources_marks_exact_match_infeasible(self) -> None:
        payload = _diagnostic_payload(
            sources=[
                {"source": "events.mechanism_family",
                 "present": False, "rows_with_value": 0},
                {"source": "curated_candidates.mechanism_family",
                 "present": False, "rows_with_value": 0},
            ],
        )
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        infeasible_ids = {p["path_id"] for p in report["infeasible_paths"]}
        self.assertIn(_PATH_EXACT_MATCH, infeasible_ids)
        # Reason must mention zero sources / no enrichment source.
        entry = next(
            p for p in report["infeasible_paths"]
            if p["path_id"] == _PATH_EXACT_MATCH
        )
        self.assertIn("source", entry["reason_infeasible"].lower())

    def test_sources_but_no_matches_marks_exact_match_infeasible(self) -> None:
        payload = _diagnostic_payload(
            sources=[
                {"source": "events.mechanism_family",
                 "present": True, "rows_with_value": 5},
                {"source": "curated_candidates.mechanism_family",
                 "present": False, "rows_with_value": 0},
            ],
            possible_matches=[],
            enrichment_gaps=[
                {"inbox_headline": "A", "gap_reason": "no match"},
            ],
        )
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        infeasible_ids = {p["path_id"] for p in report["infeasible_paths"]}
        self.assertIn(_PATH_EXACT_MATCH, infeasible_ids)

    def test_partial_coverage_marks_exact_match_infeasible(self) -> None:
        payload = _diagnostic_payload(
            sources=[
                {"source": "events.mechanism_family",
                 "present": True, "rows_with_value": 5},
            ],
            possible_matches=[
                {"inbox_headline": "A", "match_type": "exact"},
            ],
            enrichment_gaps=[
                {"inbox_headline": "B", "gap_reason": "no match"},
            ],
        )
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        infeasible_ids = {p["path_id"] for p in report["infeasible_paths"]}
        self.assertIn(_PATH_EXACT_MATCH, infeasible_ids)

    def test_full_coverage_marks_exact_match_feasible(self) -> None:
        payload = _diagnostic_payload(
            candidates_checked=2,
            sources=[
                {"source": "events.mechanism_family",
                 "present": True, "rows_with_value": 5},
            ],
            possible_matches=[
                {"inbox_headline": "A", "match_type": "exact"},
                {"inbox_headline": "B", "match_type": "normalized"},
            ],
            enrichment_gaps=[],
        )
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        feasible_ids = {p["path_id"] for p in report["feasible_paths"]}
        self.assertIn(_PATH_EXACT_MATCH, feasible_ids)
        # Even when exact-match is technically feasible, the planner
        # still recommends the artifact gate as the safest default.
        self.assertEqual(
            report["recommended_path"], _PATH_ARTIFACT_GATE,
        )


# ---------------------------------------------------------------------------
# Recommended path
# ---------------------------------------------------------------------------


class TestRecommendedPath(unittest.TestCase):
    def test_default_recommendation_is_artifact_gate(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        self.assertEqual(
            report["recommended_path"], _PATH_ARTIFACT_GATE,
        )

    def test_recommendation_drawn_from_feasible_paths(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        feasible_ids = {p["path_id"] for p in report["feasible_paths"]}
        self.assertIn(report["recommended_path"], feasible_ids)


# ---------------------------------------------------------------------------
# Required schema changes
# ---------------------------------------------------------------------------


class TestRequiredSchemaChanges(unittest.TestCase):
    def test_artifact_gate_schema_changes_cite_real_surfaces(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        joined_surfaces = " | ".join(
            c["surface"] for c in report["required_schema_changes"]
        )
        # Required: cite at least the artifacts directory, the
        # inbox file, and the Section C route surface.
        self.assertIn("artifacts/", joined_surfaces)
        self.assertIn("news_inbox.json", joined_surfaces)
        self.assertIn("routes/movers.py", joined_surfaces)

    def test_schema_changes_are_nonempty_for_recommended_path(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        self.assertGreater(len(report["required_schema_changes"]), 0)


# ---------------------------------------------------------------------------
# False-positive risks
# ---------------------------------------------------------------------------


class TestFalsePositiveRisks(unittest.TestCase):
    def test_risks_listed_for_each_path(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        joined = " | ".join(report["false_positive_risks"])
        # Each path catalogue entry has a corresponding risk bullet.
        self.assertIn(_PATH_EXACT_MATCH, joined)
        self.assertIn(_PATH_INGESTION_ALLOW_LIST, joined)
        self.assertIn(_PATH_ARTIFACT_GATE, joined)
        self.assertIn(_PATH_MANUAL_REVIEW_QUEUE, joined)
        self.assertIn(_PATH_FUZZY_LLM, joined)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _build(self) -> dict[str, Any]:
        payload = _diagnostic_payload(
            candidates_checked=3,
            sources=[
                {"source": "events.mechanism_family",
                 "present": True, "rows_with_value": 4},
            ],
            possible_matches=[
                {"inbox_headline": "A", "match_type": "exact"},
            ],
            enrichment_gaps=[
                {"inbox_headline": "B", "gap_reason": "no match"},
                {"inbox_headline": "C", "gap_reason": "no match"},
            ],
        )
        with _patch_diagnostic(payload):
            return cli.run_section_c_daily_mechanism_enrichment_plan()

    def test_no_banned_words_in_json_render(self) -> None:
        report = self._build()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, blob,
                             f"banned token {term!r} in JSON render")

    def test_no_banned_words_in_text_render(self) -> None:
        report = self._build()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, text,
                             f"banned token {term!r} in text render")


# ---------------------------------------------------------------------------
# Propagation of upstream diagnostic state
# ---------------------------------------------------------------------------


class TestDiagnosticPropagation(unittest.TestCase):
    def test_candidates_checked_propagates(self) -> None:
        payload = _diagnostic_payload(candidates_checked=7)
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        self.assertEqual(report["candidates_checked"], 7)

    def test_warnings_propagate_with_prefix(self) -> None:
        payload = _diagnostic_payload(
            warnings=["inbox file not found at 'news_inbox.json'"],
        )
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        joined = " | ".join(report["warnings"])
        self.assertIn("upstream diagnostic", joined)
        self.assertIn("inbox file not found", joined)

    def test_errors_propagate_and_flip_ok(self) -> None:
        payload = _diagnostic_payload(
            errors=["upstream broke during fetch"],
        )
        # The diagnostic carried errors, so the planner's `ok` flips
        # to False and the error is prefixed.
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        self.assertFalse(report["ok"])
        joined = " | ".join(report["errors"])
        self.assertIn("upstream diagnostic", joined)

    def test_seam_exception_is_caught_and_surfaced(self) -> None:
        with patch.object(
            cli, "_build_enrichment_diagnostic",
            side_effect=RuntimeError("simulated diagnostic failure"),
        ):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        self.assertFalse(report["ok"])
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("diagnostic", joined)
        self.assertIn("runtimeerror", joined)
        # Even when the upstream raised, the envelope keys are intact
        # so downstream consumers always see a stable shape.
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))


# ---------------------------------------------------------------------------
# Source-status normalisation
# ---------------------------------------------------------------------------


class TestSourceStatusNormalisation(unittest.TestCase):
    def test_missing_sources_list_emits_canonical_zero_rows(self) -> None:
        payload = _diagnostic_payload()
        payload["enrichment_sources_available"] = "not a list"
        with _patch_diagnostic(payload):
            report = cli.run_section_c_daily_mechanism_enrichment_plan()
        names = {s["source"] for s in report["enrichment_source_status"]}
        self.assertIn("events.mechanism_family", names)
        self.assertIn("curated_candidates.mechanism_family", names)
        for s in report["enrichment_source_status"]:
            self.assertFalse(s["present"])
            self.assertEqual(s["rows_with_value"], 0)
        # A warning surfaces so the operator notices.
        joined = " | ".join(report["warnings"]).lower()
        self.assertIn("enrichment_sources_available", joined)


# ---------------------------------------------------------------------------
# No-paid-surface import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in (
            "yfinance", "anthropic", "openai", "fastapi",
            "FastAPI", "APIRouter", "market_data",
        ):
            self.assertFalse(
                hasattr(cli, attr),
                f"planner must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            rc, output = self._run(["--json"])
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(rc, 0)

    def test_text_render_does_not_crash(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            rc, output = self._run([])
        self.assertEqual(rc, 0)
        self.assertIn("enrichment", output.lower())

    def test_errors_in_envelope_yield_nonzero_exit(self) -> None:
        payload = _diagnostic_payload(errors=["simulated upstream error"])
        with _patch_diagnostic(payload):
            rc, _ = self._run(["--json"])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

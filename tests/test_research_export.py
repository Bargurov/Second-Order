"""Tests for research_export — bundle + markdown of saved study runs."""

from __future__ import annotations

import unittest

from research_export import (
    SUPPORTED_STUDY_TYPES,
    build_research_bundle,
    format_research_markdown,
    replay_study,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ticker(role: str, r5: float | None, r20: float | None) -> dict:
    return {"symbol": "X", "role": role, "return_5d": r5, "return_20d": r20}


def _event(
    eid: int,
    family: str = "tariff",
    stage: str = "confirmed",
    tickers=None,
    regime: dict | None = None,
    date: str | None = None,
) -> dict:
    ev = {
        "id": eid,
        "headline": f"Event {eid}",
        "event_date": date or f"2025-01-{eid:02d}",
        "timestamp": (date or f"2025-01-{eid:02d}") + "T12:00:00Z",
        "mechanism_family": family,
        "stage": stage,
        "persistence": "medium",
        "market_tickers": tickers or [_ticker("beneficiary", 2.0, 4.0)],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["TSLA"],
    }
    if regime is not None:
        ev["regime_snapshot"] = regime
    return ev


# ---------------------------------------------------------------------------
# replay_study — per-type contracts
# ---------------------------------------------------------------------------

class TestReplayStudy(unittest.TestCase):
    def test_unknown_type_returns_error(self):
        r = replay_study("not_a_type", {}, [])
        self.assertIsNone(r["output"])
        self.assertIn("unknown", r["error"])

    def test_cohort_comparison_runs_end_to_end(self):
        events = (
            [_event(i, "tariff") for i in range(1, 6)]
            + [_event(i, "sanction") for i in range(10, 15)]
        )
        r = replay_study(
            "cohort_comparison",
            {"filter_a": {"family": "tariff"}, "filter_b": {"family": "sanction"}},
            events,
        )
        self.assertIsNone(r["error"])
        self.assertIn("dimensions", r["output"])
        self.assertIn("divergence_score", r["output"])

    def test_scenario_pack_research_runs(self):
        events = [_event(i, "tariff") for i in range(1, 6)]
        r = replay_study(
            "scenario_pack_research",
            {"pack_name": "tariff_cycle"},
            events,
        )
        self.assertIsNone(r["error"])
        self.assertIn("repricing_path", r["output"])
        self.assertIn("persistence", r["output"])

    def test_correlation_study_runs(self):
        events = [_event(i, "tariff") for i in range(1, 6)]
        r = replay_study("correlation_study", {}, events)
        self.assertIsNone(r["error"])
        self.assertIn("family_cooccurrence", r["output"])

    def test_cascade_view_runs(self):
        events = [_event(i, "tariff") for i in range(1, 8)]
        r = replay_study("cascade_view", {}, events)
        self.assertIsNone(r["error"])
        self.assertIn("edges", r["output"])
        self.assertIn("nodes", r["output"])
        self.assertIn("filter", r["output"])

    def test_cascade_view_respects_active_only(self):
        events = [_event(i, "tariff") for i in range(1, 8)]
        r = replay_study(
            "cascade_view",
            {"active_only": True},
            events,
        )
        self.assertIsNone(r["error"])
        for edge in r["output"]["edges"]:
            self.assertTrue(edge["active"])

    def test_cascade_view_respects_family_filter(self):
        events = (
            [_event(i, "tariff") for i in range(1, 5)]
            + [_event(i, "sanction") for i in range(10, 14)]
        )
        r = replay_study("cascade_view", {"family": "tariff"}, events)
        self.assertIsNone(r["error"])
        # Every surviving edge must connect at least one tariff node.
        by_id = {n["id"]: n for n in r["output"]["nodes"]}
        for edge in r["output"]["edges"]:
            self.assertTrue(
                by_id[edge["parent_id"]]["mechanism_family"] == "tariff"
                or by_id[edge["child_id"]]["mechanism_family"] == "tariff"
            )

    def test_cascade_view_min_weight_filter(self):
        events = [_event(i, "tariff") for i in range(1, 8)]
        r = replay_study("cascade_view", {"min_weight": 0.5}, events)
        self.assertIsNone(r["error"])
        for edge in r["output"]["edges"]:
            self.assertGreaterEqual(edge["weight"], 0.5)

    def test_replay_never_raises_on_bad_config(self):
        # scenario_pack_research with no pack_name — composer handles
        # gracefully and returns an empty cohort.
        r = replay_study("scenario_pack_research", {}, [])
        self.assertIsNotNone(r["output"] or r["error"])
        # Either path is acceptable: replay catches the exception if any.

    def test_replay_captures_exception(self):
        # Passing a non-dict config path through cohort_comparison triggers
        # validation — we should capture it rather than raise.
        events = [_event(1)]
        r = replay_study(
            "cohort_comparison",
            {"filter_a": {"family": "not_a_family"}, "filter_b": {}},
            events,
        )
        # Composer currently raises ValueError for unknown family → captured.
        self.assertIsNone(r["output"])
        self.assertIsNotNone(r["error"])


# ---------------------------------------------------------------------------
# build_research_bundle
# ---------------------------------------------------------------------------

class TestBundle(unittest.TestCase):
    def test_empty_studies_yields_empty_bundle(self):
        b = build_research_bundle([], [])
        self.assertEqual(b["counts"]["studies"], 0)
        self.assertEqual(b["studies"], [])
        self.assertIn("generated_at", b)

    def test_none_studies_yields_empty_bundle(self):
        b = build_research_bundle([], None)
        self.assertEqual(b["counts"]["studies"], 0)

    def test_none_events_safe(self):
        b = build_research_bundle(None, [{
            "study_type": "scenario_pack_research",
            "config": {"pack_name": "tariff_cycle"},
        }])
        self.assertEqual(b["total_events"], 0)
        self.assertEqual(b["counts"]["studies"], 1)

    def test_multi_study_bundle(self):
        events = [_event(i, "tariff") for i in range(1, 6)]
        b = build_research_bundle(events, [
            {"study_type": "scenario_pack_research",
             "name": "Tariffs", "config": {"pack_name": "tariff_cycle"}},
            {"study_type": "correlation_study",
             "name": "Correlations", "config": {}},
            {"study_type": "cascade_view",
             "name": "Graph", "config": {"active_only": True}},
        ])
        self.assertEqual(b["counts"]["studies"], 3)
        self.assertEqual(b["counts"]["succeeded"], 3)
        for entry in b["studies"]:
            self.assertIsNone(entry["error"])
            self.assertIsNotNone(entry["output"])

    def test_non_dict_study_captured_as_error(self):
        b = build_research_bundle([], ["garbage", None, 42])
        self.assertEqual(b["counts"]["studies"], 3)
        self.assertEqual(b["counts"]["errored"], 3)
        for entry in b["studies"]:
            self.assertEqual(entry["error"], "non-dict study spec")

    def test_bundle_preserves_provenance(self):
        events = [_event(i, "tariff") for i in range(1, 5)]
        b = build_research_bundle(events, [{
            "id": 7,
            "name": "My Tariff View",
            "description": "Tariff cycle snapshot",
            "study_type": "scenario_pack_research",
            "config": {"pack_name": "tariff_cycle"},
        }])
        entry = b["studies"][0]
        self.assertEqual(entry["id"], 7)
        self.assertEqual(entry["name"], "My Tariff View")
        self.assertEqual(entry["description"], "Tariff cycle snapshot")
        self.assertEqual(entry["config"], {"pack_name": "tariff_cycle"})

    def test_unknown_type_flagged_as_error_not_raised(self):
        b = build_research_bundle([], [{
            "study_type": "invented_type", "config": {},
        }])
        self.assertEqual(b["counts"]["errored"], 1)
        self.assertIn("unknown", b["studies"][0]["error"])


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

class TestMarkdown(unittest.TestCase):
    def test_empty_bundle_renders(self):
        md = format_research_markdown({"generated_at": "x", "total_events": 0,
                                       "studies": [], "counts": {}})
        self.assertIn("Research Export", md)

    def test_none_bundle_returns_empty(self):
        self.assertEqual(format_research_markdown(None), "")

    def test_bundle_with_comparison_rendered(self):
        events = (
            [_event(i, "tariff") for i in range(1, 6)]
            + [_event(i, "sanction") for i in range(10, 15)]
        )
        bundle = build_research_bundle(events, [{
            "name": "Comparison",
            "study_type": "cohort_comparison",
            "config": {
                "filter_a": {"family": "tariff"},
                "filter_b": {"family": "sanction"},
            },
        }])
        md = format_research_markdown(bundle)
        self.assertIn("Comparison", md)
        self.assertIn("divergence", md.lower())
        self.assertIn("| Axis |", md)

    def test_bundle_with_scenario_rendered(self):
        events = [_event(i, "tariff") for i in range(1, 6)]
        bundle = build_research_bundle(events, [{
            "name": "Tariff cycle",
            "study_type": "scenario_pack_research",
            "config": {"pack_name": "tariff_cycle"},
        }])
        md = format_research_markdown(bundle)
        self.assertIn("Tariff cycle", md)
        self.assertIn("typical repricing", md.lower())

    def test_bundle_with_cascade_rendered(self):
        events = [_event(i, "tariff") for i in range(1, 6)]
        bundle = build_research_bundle(events, [{
            "name": "Graph",
            "study_type": "cascade_view",
            "config": {},
        }])
        md = format_research_markdown(bundle)
        self.assertIn("nodes=", md)
        self.assertIn("active_edges=", md)

    def test_error_entries_surfaced_in_markdown(self):
        bundle = build_research_bundle([], [{
            "name": "Broken",
            "study_type": "invented_type",
            "config": {},
        }])
        md = format_research_markdown(bundle)
        self.assertIn("**error:**", md)
        self.assertIn("unknown", md)

    def test_markdown_ends_with_newline(self):
        bundle = build_research_bundle([], [])
        md = format_research_markdown(bundle)
        self.assertTrue(md.endswith("\n"))


class TestPortfolioViewMarkdown(unittest.TestCase):
    """Markdown formatter for the ``portfolio_view`` study type — fills
    the ``no markdown renderer`` gap and pins the filter-echo + table
    contract.  Drives the renderer through pre-built bundles so the
    test is independent of the live mover slices and the engine
    composer."""

    def _bundle(self, output: dict) -> dict:
        return {
            "generated_at": "2026-04-28T12:00:00",
            "total_events": output.get("total_considered", 0),
            "counts": {"studies": 1, "succeeded": 1, "errored": 0},
            "studies": [{
                "name":       "Saved view",
                "study_type": "portfolio_view",
                "config":     {},
                "output":     output,
                "error":      None,
            }],
        }

    def test_renderer_replaces_no_renderer_fallback(self):
        """Regression guard for the dispatch table.  Before this task
        the fallback line ``_(no markdown renderer for 'portfolio_view')_``
        leaked into every markdown export of a portfolio_view."""
        md = format_research_markdown(self._bundle({
            "filters": {}, "items": [],
            "total_considered": 0, "total_matched": 0,
        }))
        self.assertNotIn("no markdown renderer", md)
        self.assertIn("matched", md)

    def test_filter_echo_includes_engine_phase_filters(self):
        md = format_research_markdown(self._bundle({
            "filters": {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
            "items": [],
            "total_considered": 5, "total_matched": 0,
        }))
        self.assertIn("**filters:**", md)
        self.assertIn("quality_tier=actionable", md)
        self.assertIn("tradable=yes", md)
        self.assertIn("mechanism_subtype=tariff", md)

    def test_filter_echo_omits_absent_filters(self):
        """A saved view that pinned just one engine filter should
        echo only that filter — no placeholder for the others."""
        md = format_research_markdown(self._bundle({
            "filters": {"quality_tier": "watch_only"},
            "items": [], "total_considered": 5, "total_matched": 0,
        }))
        self.assertIn("quality_tier=watch_only", md)
        self.assertNotIn("tradable=", md)
        self.assertNotIn("mechanism_subtype=", md)

    def test_filter_echo_combines_engine_and_legacy_filters(self):
        md = format_research_markdown(self._bundle({
            "filters": {
                "quality_tier":    "actionable",
                "thesis_state":    "confirming",
                "low_information": False,
            },
            "items": [], "total_considered": 5, "total_matched": 0,
        }))
        self.assertIn("quality_tier=actionable", md)
        self.assertIn("thesis_state=confirming", md)
        self.assertIn("low_information=no", md)

    def test_no_filters_renders_explanatory_line(self):
        md = format_research_markdown(self._bundle({
            "filters": {}, "items": [],
            "total_considered": 0, "total_matched": 0,
        }))
        self.assertIn("no filters", md)

    def test_items_render_in_table_with_engine_phase_columns(self):
        md = format_research_markdown(self._bundle({
            "filters": {"quality_tier": "actionable"},
            "items": [{
                "id":                1,
                "event_date":        "2026-04-21",
                "headline":          "Tariff escalation announced",
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
                "thesis_state":      "confirming",
                "proof_quality":     "proof_backed",
            }],
            "total_considered": 5, "total_matched": 1,
        }))
        self.assertIn("| id |", md)
        self.assertIn("| tier |", md)
        self.assertIn("| tradable |", md)
        self.assertIn("| subtype |", md)
        self.assertIn("Tariff escalation announced", md)
        self.assertIn("actionable", md)
        self.assertIn("tariff", md)
        # tradable=true → "yes" cell
        self.assertIn("| yes |", md)

    def test_count_summary_uses_replay_totals(self):
        md = format_research_markdown(self._bundle({
            "filters": {"quality_tier": "watch_only"},
            "items": [],
            "total_considered": 12, "total_matched": 3,
        }))
        self.assertIn("matched **3**", md)
        self.assertIn("of 12 archive events", md)

    def test_pipe_in_headline_does_not_break_table(self):
        """A literal ``|`` in a headline must be escaped so it doesn't
        spawn a phantom column in the markdown table."""
        md = format_research_markdown(self._bundle({
            "filters": {},
            "items": [{
                "id": 7, "event_date": "2026-01-01",
                "headline": "Fed | hike | shock",
                "quality_tier": "watch_only",
                "tradable": False, "mechanism_subtype": None,
                "thesis_state": "neutral", "proof_quality": "no_proof",
            }],
            "total_considered": 1, "total_matched": 1,
        }))
        self.assertIn("Fed \\| hike \\| shock", md)

    def test_table_caps_at_max_rows_and_notes_overflow(self):
        items = [{
            "id": i, "event_date": "2026-04-01",
            "headline": f"Event {i}",
            "quality_tier": "actionable",
            "tradable": True, "mechanism_subtype": "tariff",
            "thesis_state": "confirming", "proof_quality": "proof_backed",
        } for i in range(1, 31)]
        md = format_research_markdown(self._bundle({
            "filters": {}, "items": items,
            "total_considered": 30, "total_matched": 30,
        }))
        # The cap is 25 rows; a 30-event payload must surface 5 omitted.
        self.assertIn("+5 more matched events omitted", md)
        # And the 30th row must NOT appear in the table.
        self.assertNotIn("Event 30", md)

    def test_end_to_end_replay_to_markdown_round_trip(self):
        """Save → replay → markdown bundle: catches a regression where
        the dispatch table lookup or the replay output shape drifts."""
        from unittest.mock import patch
        events = [
            {"id": 1, "headline": "h1", "mechanism_summary": "x"},
            {"id": 2, "headline": "h2", "mechanism_summary": "x"},
        ]

        def _fake(ev: dict) -> dict:
            return {
                1: {"quality_tier": "actionable",
                    "actionability_check": {"tradable": True},
                    "mechanism_subtype": "tariff"},
                2: {"quality_tier": "watch_only",
                    "actionability_check": {"tradable": False},
                    "mechanism_subtype": "supply_shock"},
            }[ev["id"]]

        with patch(
            "engine_phase_surface.decorate_compact", side_effect=_fake,
        ):
            bundle = build_research_bundle(events, [{
                "name":       "Tariff actionable",
                "study_type": "portfolio_view",
                "config":     {
                    "quality_tier":      "actionable",
                    "tradable":          True,
                    "mechanism_subtype": "tariff",
                },
            }])
            md = format_research_markdown(bundle)
        self.assertIn("Tariff actionable", md)
        self.assertIn("quality_tier=actionable", md)
        self.assertIn("h1", md)
        self.assertNotIn("h2", md)
        self.assertNotIn("no markdown renderer", md)


# ---------------------------------------------------------------------------
# Contract sanity
# ---------------------------------------------------------------------------

class TestContract(unittest.TestCase):
    def test_supported_types_match_saved_studies(self):
        for t in SUPPORTED_STUDY_TYPES:
            self.assertIn(t, (
                "cohort_comparison",
                "correlation_study",
                "scenario_pack_research",
                "cascade_view",
                "portfolio_view",
            ))

    def test_bundle_shape_stable(self):
        b = build_research_bundle([], [])
        for key in ("generated_at", "total_events", "studies", "counts"):
            self.assertIn(key, b)
        for key in ("studies", "errored", "succeeded"):
            self.assertIn(key, b["counts"])


if __name__ == "__main__":
    unittest.main()

"""Focused tests for the country vulnerability backdrop injection
into the analysis prompt.

Pins the task contract:

  * Country profile present → the backdrop block is attached to
    ``macro_context`` and carries exactly the five task-pinned
    fields (external_balance_risk, import_shock_risk,
    commodity_dependence, overall_vulnerability, rationale).
  * No-profile fallback → base ``macro_context`` is passed through
    byte-identical; no new lines are added.
  * Prompt context is NOT added on non-country events.
  * ``analyze_event`` output shape is unchanged in every case (the
    injection happens upstream in the prompt only).
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import country_context  # noqa: E402
from country_context import (  # noqa: E402
    build_country_backdrop_for_prompt,
    find_country_in_headline,
)


_PINNED_FIELDS = (
    "external_balance_risk",
    "import_shock_risk",
    "commodity_dependence",
    "overall_vulnerability",
    "rationale",
)


# ---------------------------------------------------------------------------
# 1. Country-matcher behaviour
# ---------------------------------------------------------------------------

class TestFindCountryInHeadline(unittest.TestCase):
    def test_matches_canonical_single_word_country(self) -> None:
        self.assertEqual(
            find_country_in_headline("Turkey lira slumps on CPI print"),
            "Turkey",
        )

    def test_matches_multi_word_country(self) -> None:
        self.assertEqual(
            find_country_in_headline(
                "South Africa reserves dip as rand weakens",
            ),
            "South Africa",
        )

    def test_match_is_case_insensitive(self) -> None:
        self.assertEqual(
            find_country_in_headline("TURKEY announces rate decision"),
            "Turkey",
        )

    def test_alias_resolves_to_canonical(self) -> None:
        # ``Turkiye`` alias → Turkey fixture.
        self.assertEqual(
            find_country_in_headline("Turkiye unveils new FX measures"),
            "Turkey",
        )

    def test_no_match_on_unrelated_headline(self) -> None:
        self.assertIsNone(find_country_in_headline(
            "Tech stocks rally as bond yields slip",
        ))

    def test_no_false_positive_on_substring(self) -> None:
        # "Chile" must not match "chilean" header with word boundaries.
        # (Using a constructed case to pin the \b guard.)
        self.assertEqual(
            find_country_in_headline("Chile copper exports climb"),
            "Chile",
        )
        # Embedded in another word — no match.
        self.assertIsNone(
            find_country_in_headline("Chilean autos gain on subsidy"),
        )

    def test_empty_headline_returns_none(self) -> None:
        self.assertIsNone(find_country_in_headline(""))
        self.assertIsNone(find_country_in_headline(None))

    def test_longer_name_wins_over_shorter_substring(self) -> None:
        # If a headline mentions both "South Africa" and "Africa",
        # the fixture-sorted matcher should prefer the multi-word
        # canonical.  Africa isn't a fixture key, but this pins the
        # descending-length registration order.
        self.assertEqual(
            find_country_in_headline(
                "South Africa-led bloc discusses Africa-wide trade deal",
            ),
            "South Africa",
        )


# ---------------------------------------------------------------------------
# 2. Prompt-block builder: shape + content
# ---------------------------------------------------------------------------

class TestBuildCountryBackdropForPrompt(unittest.TestCase):
    def test_profile_present_emits_all_pinned_fields(self) -> None:
        block = build_country_backdrop_for_prompt(
            "Turkey lira hits fresh low on external-balance concerns",
        )
        self.assertTrue(block)
        # The compact text must carry every task-pinned field by name.
        for key in _PINNED_FIELDS:
            # Fields are rendered with underscores replaced by spaces
            # in the label (e.g. "External balance risk").  Match on
            # the distinctive token present in the label.
            label_token = key.split("_")[0].lower()
            self.assertIn(label_token, block.lower(),
                          msg=f"missing label for {key!r} in block:\n{block}")

    def test_profile_present_is_compact_multiline(self) -> None:
        block = build_country_backdrop_for_prompt(
            "Turkey central bank flags external debt pressure",
        )
        self.assertTrue(block)
        # Header + four risk lines + optional context = at most 6 lines.
        lines = block.splitlines()
        self.assertGreaterEqual(len(lines), 5)
        self.assertLessEqual(len(lines), 6)
        self.assertIn("Turkey", lines[0])

    def test_reserve_stress_case_surfaces_fragile(self) -> None:
        """Turkey's fixture encodes thin reserves + severe ext-debt +
        severe fuel dependence — overall must land ``fragile`` so the
        prompt signals the import-shock / reserve-stress case."""
        block = build_country_backdrop_for_prompt(
            "Turkey FX reserves drop as lira comes under pressure",
        )
        self.assertIn("fragile", block)

    def test_empty_headline_returns_empty_string(self) -> None:
        self.assertEqual(build_country_backdrop_for_prompt(""), "")
        self.assertEqual(build_country_backdrop_for_prompt(None), "")


# ---------------------------------------------------------------------------
# 3. No-profile fallback: non-country events leave the prompt alone
# ---------------------------------------------------------------------------

class TestNoProfileFallback(unittest.TestCase):
    def test_non_country_headline_returns_empty(self) -> None:
        self.assertEqual(build_country_backdrop_for_prompt(
            "Fed speakers rotate hawkish in May",
        ), "")

    def test_country_not_in_backdrop_fixture_returns_empty(self) -> None:
        """Even when country_profiles knows a country, the prompt
        helper only fires when the compact backdrop fixture has a
        row — a broader profiles-only country must not silently
        leak an empty block."""
        # "Poland" is in country_profiles but NOT in
        # country_backdrop.COUNTRY_BACKDROP_FIXTURE.  No match.
        self.assertEqual(build_country_backdrop_for_prompt(
            "Poland flags gas storage levels",
        ), "")

    def test_fixture_misses_collapse_to_empty(self) -> None:
        # Safety net: point the matcher at a name that isn't a
        # fixture key to prove the ``None`` path.
        with mock.patch(
            "country_context.find_country_in_headline",
            return_value="Atlantis",
        ):
            self.assertEqual(build_country_backdrop_for_prompt(
                "Atlantis issues sovereign bond",
            ), "")


# ---------------------------------------------------------------------------
# 4. Route-level: macro_context is enriched only for country events
# ---------------------------------------------------------------------------

class TestAnalyzeRouteInjectsBackdrop(unittest.TestCase):
    """End-to-end contract: calling POST /analyze with a country
    headline passes a macro_context that carries the backdrop block
    to ``analyze_event``; a non-country headline leaves macro_context
    untouched so the prompt is byte-identical to the pre-task path."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import api as _api
        self.client = TestClient(_api.app)
        self._api = _api

        # Capture the AnalyzeEventInput the route hands to analyze_event
        # without making a live LLM call.  Returning a "mock" response
        # short-circuits the rest of the analyze pipeline (market
        # fetches / overlays / persistence) via
        # ``api._mock_failure_response``.
        self._captured: dict = {}

        def _fake_analyze_event(inp, *a, **kw):  # noqa: ARG001
            self._captured["macro_context"] = getattr(inp, "macro_context", "")
            self._captured["headline"] = getattr(inp, "headline", "")
            # Return a mock-shaped response so downstream short-circuits.
            return {
                "what_changed": "Insufficient evidence.",
                "mechanism_summary": "Insufficient evidence.",
                "beneficiaries": ["Insufficient evidence"],
                "losers": ["Insufficient evidence"],
                "beneficiary_tickers": [],
                "loser_tickers": [],
                "assets_to_watch": [],
                "confidence": "low",
                "is_mock": True,
            }

        self._patches = [
            mock.patch.object(self._api, "analyze_event",
                              side_effect=_fake_analyze_event),
            mock.patch.object(self._api, "build_macro_context_for_prompt",
                              return_value="Macro backdrop:\n- Regime: Mixed"),
            # Keep the route from short-circuiting through load-by-id
            # / find_cached_analysis — freshly-classified path exercises
            # the prompt-assembly code we want to test.
            mock.patch.object(self._api, "find_cached_analysis",
                              return_value=None),
            mock.patch.object(self._api, "load_event_by_id",
                              return_value=None),
            mock.patch.object(self._api, "classify_stage",
                              return_value="realized"),
            mock.patch.object(self._api, "classify_persistence",
                              return_value="medium"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def _post(self, headline: str) -> dict:
        r = self.client.post("/analyze",
                             json={"headline": headline, "confirm_paid": True})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_country_headline_adds_backdrop_to_macro_context(self) -> None:
        _ = self._post("Turkey lira weakens as reserves slip further")
        macro_ctx = self._captured["macro_context"]
        # Base macro context is still present.
        self.assertIn("Regime:", macro_ctx)
        # Country backdrop header + pinned fields are present.
        self.assertIn("Country vulnerability backdrop for Turkey", macro_ctx)
        self.assertIn("External balance risk:", macro_ctx)
        self.assertIn("Import shock risk:", macro_ctx)
        self.assertIn("Commodity dependence:", macro_ctx)
        self.assertIn("Overall vulnerability:", macro_ctx)

    def test_non_country_headline_leaves_macro_context_unchanged(self) -> None:
        _ = self._post("Fed speakers rotate on inflation commentary")
        macro_ctx = self._captured["macro_context"]
        # Base macro context passes through byte-stable.
        self.assertEqual(macro_ctx, "Macro backdrop:\n- Regime: Mixed")
        # No backdrop header leaked in.
        self.assertNotIn("vulnerability backdrop", macro_ctx.lower())

    def test_output_shape_stable_regardless_of_backdrop_injection(self) -> None:
        """The response keys must be identical with or without
        country-backdrop enrichment — the task forbids output-shape
        drift on this feature."""
        a = self._post("Turkey lira weakens")
        b = self._post("Fed speakers rotate")
        self.assertEqual(set(a.keys()), set(b.keys()))


if __name__ == "__main__":
    unittest.main()

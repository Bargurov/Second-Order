"""
tests/test_engine_shape_parity.py

Final engine-shape parity tests.

Three paths can produce a low-information analysis:

  1. ``analyze_event._mock`` — fired when the API key is missing or
     a non-transient call failure occurs.
  2. ``analyze_event._degraded_fallback`` — fired when the LLM did
     respond but the response was too thin to trust.
  3. The normal ``_finalize_analysis`` path that lands on the
     ``low_information`` tier via the gate.

Consumers of the output (UI, telegram bot, eval scripts) must see
the SAME shaped blocks across all three so a downstream branch on
``actionability_check.tradable`` or ``quality_warnings`` doesn't
crash on a missing field.  Differences in the *content* of each
block are expected (the mock and degraded paths carry different
narratives), but the field set and types must be identical.

Plus: the four flags ``confidence`` / ``degraded`` / ``tradable``
/ ``risk_level`` must never contradict each other on any of these
paths — a low_information output cannot be ``tradable=True``, etc.

Plus: internal scratch fields (``_raw_beneficiary_tickers`` /
``_raw_loser_tickers``) must be absent.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import (
    _degraded_fallback,
    _finalize_analysis,
    _mock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normal_low_info_output() -> dict:
    """Run a synthetic event through ``_finalize_analysis`` so it lands
    on the ``low_information`` tier via the normal gate (not via the
    ``_detect_weak_output`` → ``_degraded_fallback`` short-circuit).

    The fixture clears every ``_detect_weak_output`` check (substantive
    ``what_changed``, mechanism_summary above the floor with content
    words, ≥2 chain entries, named entities) but the mechanism prose
    matches the ``"uncertainty rises"`` vague-mechanism pattern so
    ``apply_low_information_gate`` fires with reason
    ``"filler_mechanism"``.
    """
    parsed = {
        "what_changed": (
            "A material policy change occurred affecting multiple "
            "global markets simultaneously across many sectors."
        ),
        "mechanism_summary": (
            "Uncertainty rises across markets as conditions evolve "
            "broadly throughout the global economy and various sectors."
        ),
        "beneficiaries":      ["TechCorp"],
        "losers":             ["BankCorp"],
        "beneficiary_tickers": ["XYZ"],
        "loser_tickers":       ["ABC"],
        "transmission_chain":  ["initial reaction step", "follow-on step"],
        "transmission_path":   [],
        "key_falsifiers":      [],
        "minimum_proof_set":   [],
        "primary_assets":      [],
        "secondary_assets":    [],
        "hedge_or_signal_assets": [],
    }
    return _finalize_analysis(
        parsed,
        headline="Generic placeholder headline",
        stage="anticipation",
        persistence="1d",
    )


# ---------------------------------------------------------------------------
# 1. Block-shape parity across the three paths
# ---------------------------------------------------------------------------
# ``actionability_check``, ``counterfactual_check`` are dicts.
# ``confidence_rationale`` is a string.
# ``quality_warnings`` is a list (closed-vocabulary tag tokens).


_BLOCK_SHAPES: dict = {
    "actionability_check":  dict,
    "counterfactual_check": dict,
    "confidence_rationale": str,
    "quality_warnings":     list,
}


class _ShapeParityMixin:
    """Helpers reused across the three path-level test classes."""

    def assert_block_shapes(self, out: dict) -> None:
        for field, expected_type in _BLOCK_SHAPES.items():
            self.assertIn(
                field, out,
                f"missing field '{field}' on {self.path_name} output",
            )
            self.assertIsInstance(
                out[field], expected_type,
                f"field '{field}' on {self.path_name} output is "
                f"{type(out[field]).__name__}, not {expected_type.__name__}",
            )

    def assert_actionability_check_keys(self, out: dict) -> None:
        ac = out["actionability_check"]
        for key in (
            "tradable",
            "why_tradable_or_not",
            "required_confirmation",
            "sizing_caveat",
            "risk_level",
            "max_confidence_before_confirmation",
            "invalidation_trigger",
        ):
            self.assertIn(
                key, ac,
                f"actionability_check missing '{key}' on {self.path_name}",
            )

    def assert_no_scratch_fields(self, out: dict) -> None:
        for scratch in ("_raw_beneficiary_tickers", "_raw_loser_tickers"):
            self.assertNotIn(
                scratch, out,
                f"scratch field '{scratch}' leaked on {self.path_name}",
            )


# ---------------------------------------------------------------------------
# 1a. Mock path
# ---------------------------------------------------------------------------


class MockPathParityTests(unittest.TestCase, _ShapeParityMixin):
    path_name = "_mock"

    def setUp(self) -> None:
        self.out = _mock("test reason")

    def test_block_shapes_present(self) -> None:
        self.assert_block_shapes(self.out)

    def test_actionability_check_full_keyset(self) -> None:
        self.assert_actionability_check_keys(self.out)

    def test_no_scratch_fields(self) -> None:
        self.assert_no_scratch_fields(self.out)


# ---------------------------------------------------------------------------
# 1b. Degraded fallback path
# ---------------------------------------------------------------------------


class DegradedFallbackParityTests(unittest.TestCase, _ShapeParityMixin):
    path_name = "_degraded_fallback"

    def setUp(self) -> None:
        self.out = _degraded_fallback(
            headline="Thin headline",
            stage="anticipation",
            persistence="1d",
            reason="thin_mechanism",
        )

    def test_block_shapes_present(self) -> None:
        self.assert_block_shapes(self.out)

    def test_actionability_check_full_keyset(self) -> None:
        self.assert_actionability_check_keys(self.out)

    def test_no_scratch_fields(self) -> None:
        self.assert_no_scratch_fields(self.out)


# ---------------------------------------------------------------------------
# 1c. Normal low-information path
# ---------------------------------------------------------------------------


class NormalLowInfoParityTests(unittest.TestCase, _ShapeParityMixin):
    path_name = "normal_low_information"

    def setUp(self) -> None:
        self.out = _normal_low_info_output()

    def test_lands_on_low_information_tier(self) -> None:
        # Anchor: if this drifts (the low-info gate stops firing), the
        # whole class is testing the wrong path.  Surface that loudly.
        self.assertEqual(
            self.out.get("quality_tier"), "low_information",
            "fixture drift: the synthetic event no longer lands on "
            "low_information — parity tests below would test the "
            "wrong path.",
        )

    def test_block_shapes_present(self) -> None:
        self.assert_block_shapes(self.out)

    def test_actionability_check_full_keyset(self) -> None:
        self.assert_actionability_check_keys(self.out)

    def test_no_scratch_fields(self) -> None:
        self.assert_no_scratch_fields(self.out)


# ---------------------------------------------------------------------------
# 2. Cross-path field-set parity — the three paths emit the same
#    block keys (and the same keys *inside* actionability_check).
# ---------------------------------------------------------------------------


class CrossPathFieldSetTests(unittest.TestCase):

    def setUp(self) -> None:
        self.mock = _mock("test reason")
        self.degraded = _degraded_fallback(
            headline="Thin headline",
            stage="anticipation",
            persistence="1d",
            reason="thin_mechanism",
        )
        self.normal = _normal_low_info_output()

    def test_top_level_parity_blocks_present_on_all_three(self) -> None:
        for field in _BLOCK_SHAPES:
            for path_name, out in (
                ("_mock", self.mock),
                ("_degraded_fallback", self.degraded),
                ("normal_low_info", self.normal),
            ):
                self.assertIn(field, out, f"missing '{field}' on {path_name}")

    def test_actionability_check_keysets_match_across_paths(self) -> None:
        keysets = {
            "_mock":               set(self.mock["actionability_check"]),
            "_degraded_fallback":  set(self.degraded["actionability_check"]),
            "normal_low_info":     set(self.normal["actionability_check"]),
        }
        # All three keysets must be identical.
        first_path, first_keys = next(iter(keysets.items()))
        for path_name, keys in keysets.items():
            self.assertEqual(
                keys, first_keys,
                f"actionability_check keysets differ between "
                f"{first_path} and {path_name}",
            )


# ---------------------------------------------------------------------------
# 3. Cross-flag consistency — confidence / degraded / tradable / risk_level
# ---------------------------------------------------------------------------
# The four flags must agree:
#   * confidence must be "low" on every low_information output
#   * tradable must be False on every low_information output
#   * risk_level must be "high" on every low_information output
#   * degraded must NOT contradict the surfacing path:
#       - _degraded_fallback: degraded=True
#       - others (mock, normal low_info): degraded falsy/absent — both
#         outputs are not "degraded LLM responses" in the technical sense
#         (a mock is a missing-key stub, a normal low-info is a real
#         analysis the gate caught)


class CrossFlagConsistencyTests(unittest.TestCase):

    def _assert_low_info_quad_consistent(self, out: dict, *, path: str) -> None:
        # confidence
        self.assertEqual(
            out.get("confidence"), "low",
            f"{path}: confidence must be 'low' on low_information",
        )
        # tradable / risk_level live inside actionability_check
        ac = out.get("actionability_check") or {}
        self.assertEqual(
            ac.get("tradable"), False,
            f"{path}: actionability_check.tradable must be False",
        )
        self.assertEqual(
            ac.get("risk_level"), "high",
            f"{path}: actionability_check.risk_level must be 'high'",
        )
        # max_confidence_before_confirmation must not contradict
        # confidence — a low-info output cannot promise "high" once
        # confirmed.
        self.assertEqual(
            ac.get("max_confidence_before_confirmation"), "low",
            f"{path}: max_confidence_before_confirmation must be 'low' "
            f"on a low_information output",
        )

    def test_mock_low_info_quad_consistent(self) -> None:
        out = _mock("test reason")
        self._assert_low_info_quad_consistent(out, path="_mock")

    def test_degraded_low_info_quad_consistent(self) -> None:
        out = _degraded_fallback(
            headline="Thin", stage="anticipation",
            persistence="1d", reason="thin_mechanism",
        )
        self._assert_low_info_quad_consistent(out, path="_degraded_fallback")
        # Degraded paths are degraded, by definition.
        self.assertTrue(out.get("degraded"))

    def test_normal_low_info_quad_consistent(self) -> None:
        out = _normal_low_info_output()
        self._assert_low_info_quad_consistent(out, path="normal_low_info")
        # A real analysis the gate caught is not "degraded"; only
        # _degraded_fallback flags itself as such.
        self.assertFalse(out.get("degraded", False))

    def test_mock_is_not_a_degraded_response(self) -> None:
        """A mock is a missing-key stub, not a degraded LLM response —
        the ``degraded`` flag must NOT fire on this path."""
        out = _mock("test reason")
        self.assertFalse(out.get("degraded", False))


# ---------------------------------------------------------------------------
# 4. Quality-tier consistency
# ---------------------------------------------------------------------------


class QualityTierParityTests(unittest.TestCase):
    """All three low_information paths must surface the same
    ``quality_tier`` enum value so consumers branching on it see a
    consistent read across paths."""

    def test_mock_carries_low_information_tier(self) -> None:
        out = _mock("test reason")
        self.assertEqual(out.get("quality_tier"), "low_information")

    def test_degraded_carries_low_information_tier(self) -> None:
        out = _degraded_fallback(
            headline="Thin", stage="anticipation",
            persistence="1d", reason="thin_mechanism",
        )
        self.assertEqual(out.get("quality_tier"), "low_information")

    def test_normal_low_info_carries_low_information_tier(self) -> None:
        out = _normal_low_info_output()
        self.assertEqual(out.get("quality_tier"), "low_information")


if __name__ == "__main__":
    unittest.main()

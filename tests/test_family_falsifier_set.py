"""
tests/test_family_falsifier_set.py

Contract tests for ``mechanism_family.falsifier_set_for_family`` — the
deterministic, family-aware ``key_falsifiers`` generator.

Covers:
  * Shape — every item carries exactly
    ``{channel, trigger_condition, timing, why_it_breaks_thesis}``.
  * Bounds — 1-3 items per real family, hard-capped at 3.
  * Specificity — ``trigger_condition`` must be concrete, not generic
    filler (``"watch markets"`` / ``"market uncertainty"`` / etc).
  * Distinct from proof set — a falsifier must not copy a proof item
    verbatim.
  * Mirrored structure with proof — same channel / timing vocabularies.
  * Stable empty behaviour for ``"none"`` and unknown family ids.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mechanism_family import (
    CHANNEL_IDS,
    FAMILY_IDS,
    FAMILY_VALIDATION_MATRIX,
    TIMING_VOCABULARY,
    falsifier_set_for_family,
    proof_set_for_family,
)


REQUIRED_KEYS = {
    "channel", "trigger_condition", "timing", "why_it_breaks_thesis",
}

REAL_FAMILIES: tuple[str, ...] = tuple(
    f for f in FAMILY_IDS if f != "none"
)


# ---------------------------------------------------------------------------
# Shape + bounds
# ---------------------------------------------------------------------------


class TestFalsifierItemShape(unittest.TestCase):
    def test_every_item_has_the_four_canonical_keys(self) -> None:
        for family in REAL_FAMILIES:
            for item in falsifier_set_for_family(family):
                self.assertEqual(
                    set(item.keys()), REQUIRED_KEYS,
                    f"{family}: item has {sorted(item.keys())}, "
                    f"expected {sorted(REQUIRED_KEYS)}",
                )

    def test_why_it_breaks_thesis_is_family_specific(self) -> None:
        """Every emitted falsifier item must carry a non-empty
        ``why_it_breaks_thesis`` string that names what the thesis
        actually requires (not a generic hedge)."""
        for family in REAL_FAMILIES:
            items = falsifier_set_for_family(family)
            for item in items:
                why = item["why_it_breaks_thesis"]
                self.assertIsInstance(why, str)
                self.assertGreater(
                    len(why), 30,
                    f"{family}: why_it_breaks_thesis too thin — {why!r}",
                )
                # Must be shaped as the family-level statement ("Thesis
                # requires …; this observation is direct evidence …").
                self.assertIn(
                    "Thesis requires", why,
                    f"{family}: why_it_breaks_thesis missing canonical form",
                )


class TestFalsifierSetBounds(unittest.TestCase):
    def test_every_real_family_has_at_least_one_item(self) -> None:
        for family in REAL_FAMILIES:
            items = falsifier_set_for_family(family)
            self.assertGreaterEqual(
                len(items), 1,
                f"{family}: {len(items)} falsifier items — need ≥1",
            )

    def test_every_family_capped_at_three_items(self) -> None:
        for family in FAMILY_IDS:
            items = falsifier_set_for_family(family)
            self.assertLessEqual(
                len(items), 3,
                f"{family}: {len(items)} items exceeds 3-item cap",
            )


# ---------------------------------------------------------------------------
# Specificity — no generic filler
# ---------------------------------------------------------------------------


GENERIC_TOKENS = (
    "watch markets", "watch the market", "market uncertainty",
    "general risk-off", "broad risk-off", "macro headwinds",
    "ambiguous signal", "unclear signal",
)


class TestNoGenericFiller(unittest.TestCase):
    def test_trigger_condition_is_not_generic(self) -> None:
        for family in REAL_FAMILIES:
            for item in falsifier_set_for_family(family):
                trig = item["trigger_condition"].lower()
                for token in GENERIC_TOKENS:
                    self.assertNotIn(
                        token, trig,
                        f"{family}: generic filler in trigger_condition: "
                        f"{item['trigger_condition']!r}",
                    )

    def test_trigger_condition_minimum_length(self) -> None:
        """A falsifier must be specific enough to be price-checkable."""
        for family in REAL_FAMILIES:
            for item in falsifier_set_for_family(family):
                self.assertGreaterEqual(
                    len(item["trigger_condition"]), 20,
                    f"{family}: trigger_condition too short to be "
                    f"actionable: {item['trigger_condition']!r}",
                )


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


class TestNoDuplicateFalsifiers(unittest.TestCase):
    def test_no_duplicate_channel_and_trigger(self) -> None:
        for family in REAL_FAMILIES:
            items = falsifier_set_for_family(family)
            keys = [
                (i["channel"], i["trigger_condition"]) for i in items
            ]
            self.assertEqual(
                len(keys), len(set(keys)),
                f"{family}: duplicate falsifier entries — {keys}",
            )


# ---------------------------------------------------------------------------
# Distinct from proof set
# ---------------------------------------------------------------------------


class TestFalsifiersDistinctFromProof(unittest.TestCase):
    def test_no_falsifier_copies_proof_verbatim(self) -> None:
        """A falsifier's trigger_condition cannot equal a proof item's
        why_it_matters — they live in structurally separate matrix
        sections (invalidation vs primary/secondary) and must stay
        distinguishable to consumers."""
        for family in REAL_FAMILIES:
            proof_blurbs = {
                (p.get("channel"), p.get("why_it_matters"))
                for p in proof_set_for_family(family)
            }
            for f_item in falsifier_set_for_family(family):
                # Trigger condition text must not be identical to any
                # proof item's why_it_matters on the same channel.
                collision_key = (
                    f_item["channel"], f_item["trigger_condition"],
                )
                self.assertNotIn(
                    collision_key, proof_blurbs,
                    f"{family}: falsifier trigger_condition matches a "
                    f"proof why_it_matters verbatim on {f_item['channel']}",
                )


# ---------------------------------------------------------------------------
# Enum discipline — channel + timing must be canonical
# ---------------------------------------------------------------------------


class TestFalsifierEnumDiscipline(unittest.TestCase):
    def test_every_channel_is_canonical(self) -> None:
        for family in REAL_FAMILIES:
            for item in falsifier_set_for_family(family):
                self.assertIn(
                    item["channel"], CHANNEL_IDS,
                    f"{family}: off-enum channel {item['channel']!r}",
                )

    def test_every_timing_is_canonical(self) -> None:
        for family in REAL_FAMILIES:
            for item in falsifier_set_for_family(family):
                self.assertIn(
                    item["timing"], TIMING_VOCABULARY,
                    f"{family}: off-enum timing {item['timing']!r}",
                )


# ---------------------------------------------------------------------------
# None / unknown — stable empty
# ---------------------------------------------------------------------------


class TestNoneAndUnknownBehaviour(unittest.TestCase):
    def test_none_family_returns_empty_list(self) -> None:
        self.assertEqual(falsifier_set_for_family("none"), [])

    def test_unknown_family_returns_empty_list(self) -> None:
        self.assertEqual(
            falsifier_set_for_family("completely_made_up_family"), [],
        )

    def test_non_string_returns_empty_list(self) -> None:
        self.assertEqual(falsifier_set_for_family(None), [])  # type: ignore[arg-type]
        self.assertEqual(falsifier_set_for_family(42), [])    # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Per-family spot checks
# ---------------------------------------------------------------------------


class TestKeyFamilySpotChecks(unittest.TestCase):
    def test_tariff_falsifier_mentions_carve_out_or_reversal(self) -> None:
        items = falsifier_set_for_family("tariff")
        text = " ".join(i["trigger_condition"].lower() for i in items)
        # Either carve-out relief or cross-commodity reversal is in the text.
        self.assertTrue(
            "carve" in text or "oppose" in text or "opposite" in text,
            f"tariff falsifiers should reference a carve-out / reversal: {text!r}",
        )

    def test_external_balance_falsifier_mentions_rescue_or_retrace(self) -> None:
        items = falsifier_set_for_family("external_balance")
        text = " ".join(i["trigger_condition"].lower() for i in items)
        self.assertTrue(
            "imf" in text or "swap line" in text or "retrace" in text
            or "recover" in text,
            f"external_balance falsifiers should reference a rescue / "
            f"retrace signal: {text!r}",
        )

    def test_regulation_falsifier_mentions_recovery_or_walk_back(self) -> None:
        items = falsifier_set_for_family("regulation")
        text = " ".join(i["trigger_condition"].lower() for i in items)
        self.assertTrue(
            "recover" in text or "carve" in text or "walk" in text
            or "lockstep" in text,
            f"regulation falsifier should reference a recovery / walk-back: {text!r}",
        )

    def test_invalidation_rowcount_aligned_with_matrix(self) -> None:
        """Sanity check: the generator emits at most what the matrix has."""
        for family in REAL_FAMILIES:
            raw = len(FAMILY_VALIDATION_MATRIX[family].get("invalidation") or [])
            emitted = len(falsifier_set_for_family(family))
            self.assertLessEqual(
                emitted, min(raw, 3),
                f"{family}: emitted {emitted} > min(raw={raw}, cap=3)",
            )


if __name__ == "__main__":
    unittest.main()

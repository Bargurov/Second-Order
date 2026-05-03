"""
tests/test_family_proof_set.py

Contract tests for ``mechanism_family.proof_set_for_family`` — the
deterministic, family-aware ``minimum_proof_set`` generator.

Covered:
  * Shape — every item carries exactly
    ``{channel, expected_direction, timing, why_it_matters}``.
  * Bounds — 2–4 items per real family, hard-capped at 4.
  * Dedupe — no two items share ``(channel, expected_direction, timing)``.
  * Mixed-channel coverage — when a family's raw matrix spans
    multiple channels, the emitted proof set must too.
  * Stable empty behaviour for ``"none"`` and unknown family ids.
  * Enum discipline — channel / timing tokens must match the canonical
    vocabularies so downstream consumers never see off-enum values.
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
    proof_set_for_family,
)


REQUIRED_KEYS = {"channel", "expected_direction", "timing", "why_it_matters"}

# Every family id except the sentinel ``"none"``.
REAL_FAMILIES: tuple[str, ...] = tuple(
    f for f in FAMILY_IDS if f != "none"
)


# ---------------------------------------------------------------------------
# Shape + bounds
# ---------------------------------------------------------------------------


class TestProofItemShape(unittest.TestCase):
    def test_every_family_item_has_the_four_canonical_keys(self) -> None:
        for family in REAL_FAMILIES:
            items = proof_set_for_family(family)
            for item in items:
                self.assertEqual(
                    set(item.keys()), REQUIRED_KEYS,
                    f"{family}: item has {sorted(item.keys())}, expected {sorted(REQUIRED_KEYS)}",
                )

    def test_why_it_matters_is_non_empty_string(self) -> None:
        for family in REAL_FAMILIES:
            for item in proof_set_for_family(family):
                self.assertIsInstance(item["why_it_matters"], str)
                self.assertGreater(
                    len(item["why_it_matters"]), 10,
                    f"{family}: why_it_matters too thin — "
                    f"{item['why_it_matters']!r}",
                )


class TestProofSetBounds(unittest.TestCase):
    def test_every_real_family_has_at_least_two_items(self) -> None:
        for family in REAL_FAMILIES:
            items = proof_set_for_family(family)
            self.assertGreaterEqual(
                len(items), 2,
                f"{family}: only {len(items)} proof items — need ≥2",
            )

    def test_every_family_capped_at_four_items(self) -> None:
        for family in FAMILY_IDS:
            items = proof_set_for_family(family)
            self.assertLessEqual(
                len(items), 4,
                f"{family}: {len(items)} items exceeds 4-item cap",
            )


# ---------------------------------------------------------------------------
# Dedupe — no generic duplicates
# ---------------------------------------------------------------------------


class TestNoDuplicateItems(unittest.TestCase):
    def test_no_duplicate_channel_direction_timing_triples(self) -> None:
        for family in REAL_FAMILIES:
            items = proof_set_for_family(family)
            keys = [
                (i["channel"], i["expected_direction"], i["timing"])
                for i in items
            ]
            self.assertEqual(
                len(keys), len(set(keys)),
                f"{family}: duplicate proof entries detected — {keys}",
            )


# ---------------------------------------------------------------------------
# Mixed-channel coverage
# ---------------------------------------------------------------------------


def _raw_matrix_channels(family: str) -> set[str]:
    """Union of channels across primary + secondary matrix rows."""
    matrix = FAMILY_VALIDATION_MATRIX.get(family) or {}
    rows = list(matrix.get("primary") or []) + list(matrix.get("secondary") or [])
    return {
        r.get("channel") for r in rows
        if isinstance(r, dict) and isinstance(r.get("channel"), str)
    }


class TestMixedChannelCoverage(unittest.TestCase):
    def test_multichannel_family_emits_multichannel_proof_set(self) -> None:
        """When the raw matrix spans ≥2 channels, the emitted set must
        also span ≥2 channels."""
        for family in REAL_FAMILIES:
            raw_channels = _raw_matrix_channels(family)
            if len(raw_channels) < 2:
                continue  # single-channel matrix — multi-channel rule N/A
            emitted = {i["channel"] for i in proof_set_for_family(family)}
            self.assertGreater(
                len(emitted), 1,
                f"{family}: raw matrix spans {raw_channels} but emitted "
                f"proof set collapsed to {emitted}",
            )


# ---------------------------------------------------------------------------
# Enum discipline
# ---------------------------------------------------------------------------


class TestProofSetEnumDiscipline(unittest.TestCase):
    def test_every_channel_is_canonical(self) -> None:
        for family in REAL_FAMILIES:
            for item in proof_set_for_family(family):
                self.assertIn(
                    item["channel"], CHANNEL_IDS,
                    f"{family}: off-enum channel {item['channel']!r}",
                )

    def test_every_timing_is_canonical(self) -> None:
        for family in REAL_FAMILIES:
            for item in proof_set_for_family(family):
                self.assertIn(
                    item["timing"], TIMING_VOCABULARY,
                    f"{family}: off-enum timing {item['timing']!r}",
                )


# ---------------------------------------------------------------------------
# None / unknown — stable empty
# ---------------------------------------------------------------------------


class TestNoneAndUnknownBehaviour(unittest.TestCase):
    def test_none_family_returns_empty_list(self) -> None:
        self.assertEqual(proof_set_for_family("none"), [])

    def test_unknown_family_returns_empty_list(self) -> None:
        self.assertEqual(
            proof_set_for_family("completely_made_up_family"), [],
        )

    def test_non_string_returns_empty_list(self) -> None:
        self.assertEqual(proof_set_for_family(None), [])  # type: ignore[arg-type]
        self.assertEqual(proof_set_for_family(123), [])   # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Per-family spot checks — the families most likely to regress
# ---------------------------------------------------------------------------


class TestKeyFamilySpotChecks(unittest.TestCase):
    def test_external_balance_covers_fx_and_credit(self) -> None:
        """EM BOP stress — fx AND credit must both appear."""
        channels = {i["channel"] for i in proof_set_for_family("external_balance")}
        self.assertIn("fx", channels)
        self.assertIn("credit", channels)

    def test_bank_stress_covers_credit_and_equities(self) -> None:
        channels = {i["channel"] for i in proof_set_for_family("bank_stress")}
        self.assertIn("credit", channels)
        self.assertIn("equities", channels)

    def test_regulation_covers_equities_and_vol(self) -> None:
        channels = {i["channel"] for i in proof_set_for_family("regulation")}
        self.assertIn("equities", channels)
        self.assertIn("vol", channels)

    def test_industrial_policy_backfills_beyond_single_primary(self) -> None:
        """industrial_policy has only 1 primary row — the backfill rule
        must pull a second distinct-channel item from secondary."""
        items = proof_set_for_family("industrial_policy")
        self.assertGreaterEqual(len(items), 2)
        channels = {i["channel"] for i in items}
        self.assertGreater(
            len(channels), 1,
            "industrial_policy should backfill to a second channel",
        )


if __name__ == "__main__":
    unittest.main()

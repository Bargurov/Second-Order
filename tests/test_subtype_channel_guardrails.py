"""
tests/test_subtype_channel_guardrails.py

Guardrails for the family / subtype channel-pack contract.

A subtype's ``primary_overrides`` and ``invalidation_extras`` rows feed
``proof_set_for_family`` and ``falsifier_set_for_family``; downstream
consumers (``low_information_gate._filter_items_to_subtype``) intersect
the resulting items with the union of the subtype's named channels and
the family's secondary cascade.  If a subtype names a channel outside
its parent family's pack, the filter silently empties the proof /
falsifier list — the desk sees "no observable trigger" rather than the
real cause ("subtype is authored against the wrong channel").

These tests lock in:
  1. The current registry passes the invariant.
  2. Every subtype's proof and falsifier output sits inside the family
     pack — proof and falsifier channel sets are symmetric.
  3. ``proof_set_for_family(family, subtype=None)`` is the same as
     ``proof_set_for_family(family)`` (empty / missing subtype is a
     no-op for backward compatibility).
  4. An invalid override channel is guarded — the validator raises a
     loud ``ValueError`` rather than silently masking the misconfig.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mechanism_family import (
    FAMILY_CHANNEL_PACKS,
    FAMILY_SUBTYPES,
    falsifier_set_for_family,
    proof_set_for_family,
    validate_subtype_channels,
)


# ---------------------------------------------------------------------------
# 1. Invariant holds for the live registry
# ---------------------------------------------------------------------------


class CurrentRegistryInvariantTests(unittest.TestCase):

    def test_validate_subtype_channels_passes_on_live_registry(self) -> None:
        # The validator runs at module import too; calling it here
        # again ensures it stays callable as a public helper.
        validate_subtype_channels()

    def test_every_subtype_override_channel_is_in_family_pack(self) -> None:
        """Sanity-walk the registry directly so a regression in
        ``validate_subtype_channels`` doesn't quietly let a bad row
        sneak through this test."""
        for family, subtypes in FAMILY_SUBTYPES.items():
            pack = FAMILY_CHANNEL_PACKS.get(family) or {}
            allowed = set(pack.get("first") or []) | set(pack.get("second") or [])
            self.assertTrue(
                allowed,
                f"family '{family}' has subtypes but no channel pack",
            )
            for subtype, meta in subtypes.items():
                for kind in ("primary_overrides", "invalidation_extras"):
                    for idx, row in enumerate(meta.get(kind) or []):
                        ch = row.get("channel")
                        self.assertIn(
                            ch, allowed,
                            f"{family}.{subtype}.{kind}[{idx}] channel "
                            f"'{ch}' must be in family pack {sorted(allowed)}",
                        )


# ---------------------------------------------------------------------------
# 2. Proof / falsifier channel symmetry per (family, subtype)
# ---------------------------------------------------------------------------


class ProofFalsifierSymmetryTests(unittest.TestCase):
    """For every registered (family, subtype) pair, the channels surfaced
    by proof_set_for_family and falsifier_set_for_family must be a
    subset of the family pack.  This is the guarantee downstream
    filters rely on — proof and falsifier always live in the same
    channel space."""

    def test_each_subtype_proof_falsifier_channels_are_within_family_pack(self) -> None:
        for family, subtypes in FAMILY_SUBTYPES.items():
            pack = FAMILY_CHANNEL_PACKS.get(family) or {}
            allowed = set(pack.get("first") or []) | set(pack.get("second") or [])
            for subtype in subtypes:
                proof = proof_set_for_family(family, subtype=subtype)
                falsifier = falsifier_set_for_family(family, subtype=subtype)
                proof_channels = {p["channel"] for p in proof}
                falsifier_channels = {f["channel"] for f in falsifier}

                self.assertTrue(
                    proof_channels.issubset(allowed),
                    f"{family}.{subtype}: proof channels {sorted(proof_channels)}"
                    f" leak outside family pack {sorted(allowed)}",
                )
                self.assertTrue(
                    falsifier_channels.issubset(allowed),
                    f"{family}.{subtype}: falsifier channels "
                    f"{sorted(falsifier_channels)} leak outside family "
                    f"pack {sorted(allowed)}",
                )

    def test_subtype_proof_set_is_non_empty_for_known_subtypes(self) -> None:
        """If a subtype is registered, the proof set must have at least
        one item — silently empty proof sets indicate a hidden channel
        misconfig that the invariant already caught, but this test
        adds a behavioural check on top."""
        for family, subtypes in FAMILY_SUBTYPES.items():
            for subtype in subtypes:
                proof = proof_set_for_family(family, subtype=subtype)
                self.assertGreater(
                    len(proof), 0,
                    f"{family}.{subtype}: proof_set_for_family returned []",
                )


# ---------------------------------------------------------------------------
# 3. Empty / missing subtype is a no-op
# ---------------------------------------------------------------------------


class EmptySubtypeNoOpTests(unittest.TestCase):

    def test_proof_set_with_none_subtype_matches_family_default(self) -> None:
        for family in FAMILY_SUBTYPES:
            family_only = proof_set_for_family(family)
            none_subtype = proof_set_for_family(family, subtype=None)
            self.assertEqual(
                none_subtype, family_only,
                f"{family}: subtype=None must match the family-level set",
            )

    def test_falsifier_set_with_none_subtype_matches_family_default(self) -> None:
        for family in FAMILY_SUBTYPES:
            family_only = falsifier_set_for_family(family)
            none_subtype = falsifier_set_for_family(family, subtype=None)
            self.assertEqual(
                none_subtype, family_only,
                f"{family}: falsifier subtype=None must match family-level set",
            )

    def test_unknown_subtype_falls_back_to_family_default(self) -> None:
        """An unrecognised subtype id must NOT empty the proof / falsifier
        sets — it should degrade to the family-level behaviour."""
        for family in FAMILY_SUBTYPES:
            family_only = proof_set_for_family(family)
            unknown = proof_set_for_family(family, subtype="not_a_real_subtype")
            self.assertEqual(unknown, family_only)


# ---------------------------------------------------------------------------
# 4. Invalid override is guarded loudly
# ---------------------------------------------------------------------------


class InvalidOverrideGuardedTests(unittest.TestCase):
    """Monkey-patch a copy of FAMILY_SUBTYPES with a bad channel and
    confirm the validator surfaces it.  Each test restores the
    registry in its tearDown so the live one stays untouched."""

    def setUp(self) -> None:
        import mechanism_family as mf
        self._mf = mf
        self._original = mf.FAMILY_SUBTYPES

    def tearDown(self) -> None:
        self._mf.FAMILY_SUBTYPES = self._original

    def test_off_pack_primary_override_channel_raises(self) -> None:
        """A primary_overrides row whose channel is NOT in the family
        pack must trip the validator."""
        bad = {
            "tariff": {
                "broken_subtype": {
                    "keywords": ("synthetic test",),
                    "primary_overrides": [
                        # "rates" is in tariff's "second" pack, not in
                        # tariff's "first" — so use a channel that's
                        # in NEITHER list to actually be off-pack.
                        # tariff pack: first=[commodities, equities, fx],
                        #             second=[rates, credit].
                        # "vol" is not in either, so this is invalid.
                        {"channel": "vol", "expected_direction": "up",
                         "timing": "1d", "named_assets": ["VXX"]},
                    ],
                },
            },
        }
        self._mf.FAMILY_SUBTYPES = bad
        with self.assertRaises(ValueError) as ctx:
            self._mf.validate_subtype_channels()
        msg = str(ctx.exception)
        self.assertIn("broken_subtype", msg)
        self.assertIn("'vol'", msg)
        self.assertIn("FAMILY_CHANNEL_PACKS['tariff']", msg)

    def test_off_pack_invalidation_extra_channel_raises(self) -> None:
        bad = {
            "supply_shock": {
                "broken_subtype": {
                    "keywords": ("synthetic",),
                    "primary_overrides": [
                        {"channel": "commodities", "expected_direction": "up"},
                    ],
                    # supply_shock pack: first=[commodities, equities],
                    #                    second=[rates, fx, credit].
                    # "vol" is not in either, so this is invalid.
                    "invalidation_extras": [
                        {"channel": "vol", "signal": "x" * 30,
                         "timing": "1d"},
                    ],
                },
            },
        }
        self._mf.FAMILY_SUBTYPES = bad
        with self.assertRaises(ValueError) as ctx:
            self._mf.validate_subtype_channels()
        self.assertIn("invalidation_extras", str(ctx.exception))
        self.assertIn("'vol'", str(ctx.exception))

    def test_missing_channel_in_override_raises(self) -> None:
        bad = {
            "tariff": {
                "broken_subtype": {
                    "primary_overrides": [
                        {"expected_direction": "up", "timing": "1d"},
                    ],
                },
            },
        }
        self._mf.FAMILY_SUBTYPES = bad
        with self.assertRaises(ValueError) as ctx:
            self._mf.validate_subtype_channels()
        self.assertIn("missing channel", str(ctx.exception))

    def test_validator_aggregates_multiple_errors(self) -> None:
        """One failing row shouldn't short-circuit reporting; a desk
        author should see every offending entry in one message."""
        bad = {
            "tariff": {
                "subtype_a": {
                    "primary_overrides": [
                        {"channel": "vol", "expected_direction": "up"},
                    ],
                },
                "subtype_b": {
                    "primary_overrides": [
                        {"channel": "made_up_channel", "expected_direction": "up"},
                    ],
                },
            },
        }
        self._mf.FAMILY_SUBTYPES = bad
        with self.assertRaises(ValueError) as ctx:
            self._mf.validate_subtype_channels()
        msg = str(ctx.exception)
        self.assertIn("subtype_a", msg)
        self.assertIn("subtype_b", msg)


if __name__ == "__main__":
    unittest.main()

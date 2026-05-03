"""
tests/test_scenario_packs.py

Contract tests for reusable scenario packs.

Covers:
  1. Registry sanity — five scenarios, every one has the required fields.
  2. Family-link invariant — every pack's ``family`` is a valid
     mechanism_family id.
  3. Repricing-pattern discipline — every phase uses a horizon from
     TIMING_VOCABULARY and a concrete description.
  4. Sector-consequences discipline — entries are {sector, rationale}
     with no tickers smuggled in.
  5. Scenario falsifiers — timing tokens are from TIMING_VOCABULARY.
  6. Composer (``compute_scenario_playbook``) —
     - joins scenario data with FAMILY_VALIDATION_MATRIX
     - de-duplicates invalidators between family + scenario with
       ``source`` provenance tag
     - unknown scenario degrades gracefully
     - deep-copy safety — caller mutation doesn't leak
  7. Specificity — the five scenarios produce distinct playbooks
     (mapping differs by scenario, not a one-size-fits-all template).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mechanism_family import (
    FAMILY_IDS,
    FAMILY_VALIDATION_MATRIX,
    TIMING_VOCABULARY,
)
from scenario_packs import (
    SCENARIO_IDS,
    SCENARIO_LABELS,
    SCENARIO_PACKS,
    compute_scenario_playbook,
    get_scenario_pack,
    is_valid_scenario,
)


# ---------------------------------------------------------------------------
# 1. Registry sanity
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):

    def test_five_scenarios_registered(self):
        self.assertEqual(len(SCENARIO_IDS), 5)
        self.assertEqual(set(SCENARIO_IDS), set(SCENARIO_PACKS.keys()))

    def test_every_scenario_has_a_label(self):
        for sid in SCENARIO_IDS:
            self.assertIn(sid, SCENARIO_LABELS)
            self.assertTrue(SCENARIO_LABELS[sid].strip())

    def test_every_pack_has_required_top_level_fields(self):
        required = {"family", "summary", "repricing_pattern",
                    "sector_consequences", "scenario_falsifiers"}
        for sid, pack in SCENARIO_PACKS.items():
            missing = required - set(pack.keys())
            self.assertFalse(missing, f"{sid} missing fields: {missing}")

    def test_is_valid_scenario(self):
        for sid in SCENARIO_IDS:
            self.assertTrue(is_valid_scenario(sid))
        self.assertFalse(is_valid_scenario("not_a_scenario"))
        self.assertFalse(is_valid_scenario(None))


# ---------------------------------------------------------------------------
# 2. Family-link invariant
# ---------------------------------------------------------------------------

class TestFamilyLinkInvariant(unittest.TestCase):
    """Every scenario pack's ``family`` field must resolve to a real
    mechanism_family id.  If this drifts the composer silently returns
    an empty matrix and the UI loses half the playbook."""

    def test_every_scenario_family_is_a_valid_family_id(self):
        for sid, pack in SCENARIO_PACKS.items():
            self.assertIn(
                pack["family"], FAMILY_IDS,
                f"scenario {sid}: family {pack['family']!r} "
                f"is not in FAMILY_IDS",
            )

    def test_every_scenario_family_has_a_validation_matrix(self):
        for sid, pack in SCENARIO_PACKS.items():
            self.assertIn(
                pack["family"], FAMILY_VALIDATION_MATRIX,
                f"scenario {sid}: family has no validation matrix entry",
            )


# ---------------------------------------------------------------------------
# 3. Repricing-pattern discipline
# ---------------------------------------------------------------------------

class TestRepricingPattern(unittest.TestCase):

    def test_every_phase_has_phase_horizon_description(self):
        required = {"phase", "horizon", "description"}
        for sid, pack in SCENARIO_PACKS.items():
            for phase in pack["repricing_pattern"]:
                missing = required - set(phase.keys())
                self.assertFalse(
                    missing,
                    f"{sid} phase {phase} missing fields: {missing}",
                )

    def test_every_phase_horizon_is_in_controlled_vocabulary(self):
        for sid, pack in SCENARIO_PACKS.items():
            for phase in pack["repricing_pattern"]:
                self.assertIn(
                    phase["horizon"], TIMING_VOCABULARY,
                    f"{sid} phase has off-vocab horizon: {phase}",
                )

    def test_descriptions_under_length_cap(self):
        for sid, pack in SCENARIO_PACKS.items():
            for phase in pack["repricing_pattern"]:
                self.assertLessEqual(
                    len(phase["description"]), 240,
                    f"{sid} phase description too long ({len(phase['description'])} chars)",
                )

    def test_repricing_pattern_is_non_empty(self):
        for sid, pack in SCENARIO_PACKS.items():
            self.assertGreaterEqual(
                len(pack["repricing_pattern"]), 2,
                f"{sid}: repricing_pattern should have ≥2 phases",
            )


# ---------------------------------------------------------------------------
# 4. Sector-consequences discipline
# ---------------------------------------------------------------------------

class TestSectorConsequences(unittest.TestCase):

    def test_entries_are_sector_rationale_pairs(self):
        required = {"sector", "rationale"}
        for sid, pack in SCENARIO_PACKS.items():
            sc = pack["sector_consequences"]
            for side in ("beneficiaries", "losers"):
                for row in sc.get(side, []):
                    missing = required - set(row.keys())
                    self.assertFalse(
                        missing,
                        f"{sid}.{side} row missing fields: {missing}",
                    )

    def test_sector_consequences_contains_no_tickers(self):
        """Tickers drift; sectors don't.  An entry is a ticker if it's
        all-caps 1-5 letters with no spaces or underscores.  The
        registry must stay sector-named."""
        def _looks_like_ticker(s: str) -> bool:
            return (
                1 <= len(s) <= 5
                and s.isalpha()
                and s.isupper()
                and "_" not in s
                and " " not in s
            )
        for sid, pack in SCENARIO_PACKS.items():
            sc = pack["sector_consequences"]
            for side in ("beneficiaries", "losers"):
                for row in sc.get(side, []):
                    self.assertFalse(
                        _looks_like_ticker(row.get("sector", "")),
                        f"{sid}.{side} has a ticker-like sector name: {row}",
                    )

    def test_each_scenario_has_beneficiaries_and_losers(self):
        for sid, pack in SCENARIO_PACKS.items():
            sc = pack["sector_consequences"]
            self.assertGreater(
                len(sc.get("beneficiaries", [])), 0,
                f"{sid}: must name at least one beneficiary sector",
            )
            self.assertGreater(
                len(sc.get("losers", [])), 0,
                f"{sid}: must name at least one loser sector",
            )


# ---------------------------------------------------------------------------
# 5. Scenario falsifier discipline
# ---------------------------------------------------------------------------

class TestScenarioFalsifiers(unittest.TestCase):

    def test_every_falsifier_has_signal_channel_timing(self):
        required = {"signal", "channel", "timing"}
        for sid, pack in SCENARIO_PACKS.items():
            for row in pack["scenario_falsifiers"]:
                missing = required - set(row.keys())
                self.assertFalse(
                    missing,
                    f"{sid} falsifier missing fields: {missing}",
                )

    def test_falsifier_timings_are_controlled(self):
        for sid, pack in SCENARIO_PACKS.items():
            for row in pack["scenario_falsifiers"]:
                self.assertIn(
                    row["timing"], TIMING_VOCABULARY,
                    f"{sid} falsifier has off-vocab timing: {row}",
                )


# ---------------------------------------------------------------------------
# 6. Composer — compute_scenario_playbook
# ---------------------------------------------------------------------------

class TestComposer(unittest.TestCase):

    def test_known_scenario_joins_scenario_and_family(self):
        playbook = compute_scenario_playbook("oil_spike")
        self.assertTrue(playbook["available"])
        self.assertEqual(playbook["scenario"], "oil_spike")
        self.assertEqual(playbook["family"], "commodity_squeeze")
        # Channel expectations are joined from the family matrix.
        channels = {c["channel"] for c in playbook["primary_channels"]}
        self.assertIn("commodities", channels)
        # Scenario-level fields are preserved.
        self.assertGreater(len(playbook["repricing_pattern"]), 0)
        self.assertGreater(len(playbook["sector_consequences"]["beneficiaries"]), 0)

    def test_unknown_scenario_degrades_to_shaped_empty(self):
        playbook = compute_scenario_playbook("not_a_scenario")
        self.assertFalse(playbook["available"])
        self.assertEqual(playbook["primary_channels"], [])
        self.assertEqual(playbook["sector_consequences"],
                         {"beneficiaries": [], "losers": []})

    def test_invalidators_carry_source_provenance(self):
        playbook = compute_scenario_playbook("oil_spike")
        sources = {row["source"] for row in playbook["invalidators"]}
        # Family always contributes; scenario should too unless the
        # scenario's falsifiers all duplicate the family list.
        self.assertIn("family", sources)

    def test_invalidators_are_deduped_across_family_and_scenario(self):
        """If a scenario falsifier exactly matches a family invalidation
        row (by signal + channel), the composer must emit it once —
        family-sourced — not duplicate it."""
        playbook = compute_scenario_playbook("oil_spike")
        keys: list[tuple] = []
        for row in playbook["invalidators"]:
            keys.append(
                ((row.get("signal") or "").strip().lower(),
                 (row.get("channel") or "").strip().lower()),
            )
        self.assertEqual(
            len(keys), len(set(keys)),
            f"invalidators list has duplicates: {keys}",
        )

    def test_scenario_falsifier_is_marked_as_scenario_source(self):
        """At least one scenario must contribute a genuinely new
        falsifier that isn't in the family matrix — otherwise the
        scenario layer isn't adding information."""
        any_scenario_added = False
        for sid in SCENARIO_IDS:
            playbook = compute_scenario_playbook(sid)
            if any(row.get("source") == "scenario"
                   for row in playbook["invalidators"]):
                any_scenario_added = True
                break
        self.assertTrue(
            any_scenario_added,
            "no scenario contributes a net-new falsifier — layer is redundant",
        )

    def test_composer_output_is_deep_copy_safe(self):
        """Callers can mutate the returned dict freely without leaking
        into the registry."""
        p1 = compute_scenario_playbook("oil_spike")
        p1["repricing_pattern"].append({"phase": "bogus", "horizon": "1d",
                                         "description": "x"})
        p1["sector_consequences"]["beneficiaries"].append(
            {"sector": "bogus", "rationale": "x"},
        )
        p2 = compute_scenario_playbook("oil_spike")
        sectors = {s["sector"] for s in p2["sector_consequences"]["beneficiaries"]}
        self.assertNotIn("bogus", sectors)
        phases = {p["phase"] for p in p2["repricing_pattern"]}
        self.assertNotIn("bogus", phases)


# ---------------------------------------------------------------------------
# 7. Specificity — the 5 scenarios must produce distinct playbooks
# ---------------------------------------------------------------------------

class TestScenarioSpecificity(unittest.TestCase):

    def test_each_scenario_maps_to_a_distinct_family(self):
        families = [SCENARIO_PACKS[sid]["family"] for sid in SCENARIO_IDS]
        # Five scenarios, five distinct families — no collisions.
        self.assertEqual(len(families), len(set(families)))

    def test_sector_consequences_differ_across_scenarios(self):
        """If two scenarios produced the same beneficiary sector set,
        the layer would be adding ceremony without value."""
        sector_sets: list[frozenset] = []
        for sid in SCENARIO_IDS:
            sc = SCENARIO_PACKS[sid]["sector_consequences"]
            ben = frozenset(s["sector"] for s in sc["beneficiaries"])
            sector_sets.append(ben)
        # At least 4 of the 5 beneficiary sector sets are distinct.
        self.assertGreaterEqual(
            len(set(sector_sets)), 4,
            f"beneficiary sector sets too similar: {sector_sets}",
        )

    def test_oil_spike_names_airlines_as_loser(self):
        pack = get_scenario_pack("oil_spike")
        loser_sectors = {s["sector"] for s in pack["sector_consequences"]["losers"]}
        self.assertIn("airlines", loser_sectors)

    def test_funding_squeeze_names_regional_banks_as_loser(self):
        pack = get_scenario_pack("funding_squeeze")
        loser_sectors = {s["sector"] for s in pack["sector_consequences"]["losers"]}
        self.assertIn("regional_banks", loser_sectors)

    def test_ceasefire_names_defense_as_loser(self):
        pack = get_scenario_pack("ceasefire_deescalation")
        loser_sectors = {s["sector"] for s in pack["sector_consequences"]["losers"]}
        self.assertIn("defense", loser_sectors)


if __name__ == "__main__":
    unittest.main()

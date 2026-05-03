"""
tests/test_family_expansion.py

Contract tests for the three newly-added mechanism families —
``industrial_policy``, ``regulation``, ``external_balance`` — and for
the matching theme coverage in the news-relevance filter.

Why the split
-------------
Family-enum expansion and keyword-coverage expansion are two separate
concerns (a headline can be relevant without the LLM having a family
to classify it under), but they ship together here because both are
part of the same "broaden topic coverage" task.  The tests are
grouped by concern so a failure points cleanly at either the classifier
taxonomy or the intake filter.

Invariants this file enforces beyond what the generic
``test_validation_matrix`` / ``test_mechanism_family`` already check:

  * Each new family has a STRUCTURALLY DISTINCT primary-channel set
    (otherwise it's a relabel of an existing family, not a real
    expansion).
  * The composer layers (``get_default_channel_pack``,
    ``compute_validation_matrix``) accept and return the new ids
    intact — no silent degradation to ``none``.
  * Concrete sample headlines for each covered theme pass
    ``news_relevance.is_relevant`` (regression safety for the
    keyword additions).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mechanism_family import (
    FAMILY_IDS,
    FAMILY_LABELS,
    FAMILY_CHANNEL_PACKS,
    FAMILY_VALIDATION_MATRIX,
    get_default_channel_pack,
)
from validation_plan import compute_validation_matrix
from news_relevance import is_relevant


# ---------------------------------------------------------------------------
# 1. Registry membership — the three new families must load everywhere.
# ---------------------------------------------------------------------------

NEW_FAMILIES = ("industrial_policy", "regulation", "external_balance")


class TestNewFamilyRegistration(unittest.TestCase):
    def test_new_families_in_enum(self) -> None:
        for fam in NEW_FAMILIES:
            self.assertIn(fam, FAMILY_IDS)

    def test_new_families_in_labels(self) -> None:
        for fam in NEW_FAMILIES:
            self.assertIn(fam, FAMILY_LABELS)
            self.assertGreater(len(FAMILY_LABELS[fam]), 0)

    def test_new_families_in_channel_packs(self) -> None:
        for fam in NEW_FAMILIES:
            self.assertIn(fam, FAMILY_CHANNEL_PACKS)
            pack = FAMILY_CHANNEL_PACKS[fam]
            self.assertGreater(
                len(pack["first"]), 0,
                f"{fam}: first pack is empty — must have ≥1 primary channel",
            )

    def test_new_families_in_validation_matrix(self) -> None:
        for fam in NEW_FAMILIES:
            self.assertIn(fam, FAMILY_VALIDATION_MATRIX)
            entry = FAMILY_VALIDATION_MATRIX[fam]
            for key in ("primary", "secondary", "false_positives",
                        "invalidation", "timing_by_channel"):
                self.assertIn(key, entry, f"{fam} missing {key!r}")
            # Primary must have at least one row — else the family can't
            # confirm anything.
            self.assertGreater(
                len(entry["primary"]), 0,
                f"{fam}: primary row list is empty",
            )

    def test_composer_layers_accept_new_families(self) -> None:
        for fam in NEW_FAMILIES:
            pack = get_default_channel_pack(fam)
            self.assertTrue(pack["first"], f"{fam} pack is empty via composer")
            m = compute_validation_matrix(fam)
            self.assertTrue(
                m["available"],
                f"{fam}: composer marked unavailable",
            )
            self.assertEqual(m["mechanism_family"], fam)


# ---------------------------------------------------------------------------
# 2. Distinctness — new families must not collapse onto existing ones.
# ---------------------------------------------------------------------------


def _primary_channels(fam: str) -> frozenset[str]:
    return frozenset(
        e["channel"] for e in FAMILY_VALIDATION_MATRIX[fam]["primary"]
    )


class TestFamilyDistinctness(unittest.TestCase):
    """Two families with identical primary-channel sets collapse into
    one — no mechanism-validation payoff from keeping them separate."""

    def test_industrial_policy_is_equity_centric(self) -> None:
        # Sector dispersion is the read — equities must lead, macro
        # channels (rates/fx) are secondary only.
        primary = _primary_channels("industrial_policy")
        self.assertIn("equities", primary)
        self.assertNotIn("rates", primary)
        self.assertNotIn("fx", primary)

    def test_regulation_is_equity_and_vol(self) -> None:
        primary = _primary_channels("regulation")
        self.assertIn("equities", primary)
        self.assertIn("vol", primary)
        # Regulation does NOT primarily move commodities — that would
        # collapse it onto supply_shock.
        self.assertNotIn("commodities", primary)

    def test_external_balance_is_fx_and_credit(self) -> None:
        primary = _primary_channels("external_balance")
        self.assertIn("fx", primary)
        self.assertIn("credit", primary)
        # External balance isn't primarily equities-driven (that's
        # industrial_policy / regulation) or commodities-driven
        # (supply_shock).
        self.assertNotIn("equities", primary)

    def test_each_new_family_has_a_unique_primary_set(self) -> None:
        sets = {fam: _primary_channels(fam) for fam in NEW_FAMILIES}
        # All three differ from each other.
        pairs = [
            ("industrial_policy", "regulation"),
            ("industrial_policy", "external_balance"),
            ("regulation", "external_balance"),
        ]
        for a, b in pairs:
            self.assertNotEqual(
                sets[a], sets[b],
                f"{a} and {b} have identical primary channels — collapse them",
            )

    def test_new_families_do_not_duplicate_existing_ones(self) -> None:
        # If industrial_policy has the same primary set as e.g. tariff
        # or policy_surprise, the new family doesn't earn its slot.
        for new in NEW_FAMILIES:
            new_set = _primary_channels(new)
            for existing in FAMILY_IDS:
                if existing in NEW_FAMILIES or existing == "none":
                    continue
                self.assertNotEqual(
                    new_set, _primary_channels(existing),
                    f"{new} primary channels identical to {existing} — "
                    f"families should be structurally distinct",
                )


# ---------------------------------------------------------------------------
# 3. False-positive discipline for the new families
# ---------------------------------------------------------------------------


class TestNewFamilyFalsePositives(unittest.TestCase):
    """Every new family must name at least one false-positive scenario
    with a distinguishing signal — otherwise the matrix doesn't help
    a reader separate a real read from a coincidental one."""

    def test_every_new_family_has_a_false_positive(self) -> None:
        for fam in NEW_FAMILIES:
            fps = FAMILY_VALIDATION_MATRIX[fam]["false_positives"]
            self.assertGreater(
                len(fps), 0,
                f"{fam}: no false_positives entries",
            )
            for row in fps:
                self.assertIn("distinguishing_signal", row)
                self.assertTrue(len(row["distinguishing_signal"]) > 15)

    def test_every_new_family_has_an_invalidation_signal(self) -> None:
        for fam in NEW_FAMILIES:
            invs = FAMILY_VALIDATION_MATRIX[fam]["invalidation"]
            self.assertGreater(
                len(invs), 0,
                f"{fam}: no invalidation entries",
            )
            for row in invs:
                self.assertIn("signal", row)
                self.assertIn("channel", row)
                self.assertIn("timing", row)


# ---------------------------------------------------------------------------
# 4. Intake keyword coverage — concrete headlines for each broader theme
# ---------------------------------------------------------------------------
# These are the headlines that should NOT have been falling off the intake
# filter before the coverage expansion.  Each one is a realistic wire
# headline drawn from the themes in the task.


_THEME_HEADLINES: dict[str, list[str]] = {
    "industrial_policy": [
        "Biden administration awards $6B in CHIPS Act production credit to TSMC Arizona fab",
        "EU green deal earmarks €40B in industrial strategy capex incentive",
        "Treasury finalises Inflation Reduction Act tax credit rules for battery plants",
        "White House expands investment credit for reshoring semiconductor capacity",
    ],
    "regulation": [
        "FTC launches merger review of pharma combination on antitrust grounds",
        "UK CMA orders consent decree blocking Big Tech acquisition",
        "Basel III capital requirement hike triggers European bank capital rules review",
        "SEC disclosure rule tightens climate risk reporting for public companies",
    ],
    "external_balance": [
        "Turkey central bank reserves drain accelerates as capital flight intensifies",
        "Argentina sovereign CDS blows out 200bp on bailout package delay",
        "Egypt hard currency debt costs surge as current account deficit widens",
        "Pakistan secures IMF swap line as forex reserves fall below one month of imports",
    ],
    "semis_supply_chain": [
        "TSMC advanced node fab capacity booked out through 2027 on AI demand",
        "Samsung foundry wins memory chip export order; ASML ships high-NA EUV tool",
        "SMIC trailing edge node capacity constrained by US chip export restrictions",
    ],
    "rate_sensitive_sectors": [
        "REIT index underperforms SPY on long duration selloff after 10Y yield breakout",
        "Homebuilder stocks tumble as mortgage rates hit cycle high",
    ],
}


class TestIntakeCoverageForNewThemes(unittest.TestCase):
    def test_industrial_policy_headlines_pass(self) -> None:
        for h in _THEME_HEADLINES["industrial_policy"]:
            self.assertTrue(
                is_relevant(h),
                f"industrial_policy headline dropped: {h!r}",
            )

    def test_regulation_headlines_pass(self) -> None:
        for h in _THEME_HEADLINES["regulation"]:
            self.assertTrue(
                is_relevant(h),
                f"regulation headline dropped: {h!r}",
            )

    def test_external_balance_headlines_pass(self) -> None:
        for h in _THEME_HEADLINES["external_balance"]:
            self.assertTrue(
                is_relevant(h),
                f"external_balance headline dropped: {h!r}",
            )

    def test_semis_supply_chain_headlines_pass(self) -> None:
        for h in _THEME_HEADLINES["semis_supply_chain"]:
            self.assertTrue(
                is_relevant(h),
                f"semis headline dropped: {h!r}",
            )

    def test_rate_sensitive_headlines_pass(self) -> None:
        for h in _THEME_HEADLINES["rate_sensitive_sectors"]:
            self.assertTrue(
                is_relevant(h),
                f"rate-sensitive headline dropped: {h!r}",
            )


# ---------------------------------------------------------------------------
# 5. Regression safety — existing lifestyle / noise headlines still reject
# ---------------------------------------------------------------------------
# Coverage expansion must not open the gates to entertainment / sports /
# casualty-only headlines; the intake filter is what keeps the LLM
# analysis queue clean.


_MUST_REJECT_HEADLINES = [
    "Celebrity couple announces engagement at awards ceremony",
    "Local family finds lost dog after week-long search",
    "15 killed in weekend road accident in rural province",
    "Pope Francis leads Easter mass at St Peter's",
    "Prediction market pegs election winner at 54 %",
    "DIARY: Reuters schedule of upcoming events Apr 25",
]


class TestRegressionRejection(unittest.TestCase):
    def test_noise_headlines_still_rejected(self) -> None:
        for h in _MUST_REJECT_HEADLINES:
            self.assertFalse(
                is_relevant(h),
                f"non-relevant headline leaked through: {h!r}",
            )


if __name__ == "__main__":
    unittest.main()

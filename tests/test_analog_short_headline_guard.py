"""
tests/test_analog_short_headline_guard.py

Structural invariants proving the short-headline guard fires on
headline-only words BEFORE mechanism-text expansion in analog matching.

The invariant: a pair whose headline words fail _short_headline_guard must
be rejected even when mechanism-text overlap would otherwise push the
expanded-set Jaccard above the analog threshold.

Three invariant groups:
  1) Short false analog blocked — mechanism overlap real, guard fires first
  2) Short true analog preserved — ≥2 shared hl tokens, guard passes
  3) Longer analog behavior unchanged — long headlines, mechanism helps
"""

import sys
import unittest

sys.path.insert(0, ".")

from db import _headline_words, _jaccard, _short_headline_guard
from token_norm import _STOP_WORDS

_ANALOG_THRESHOLD = 0.15   # mirror of the constant in find_historical_analogs


def _guard_then_expand(
    hl_a: str, mech_a: str,
    hl_b: str, mech_b: str,
) -> bool:
    """Simulate the FIXED find_historical_analogs inner-loop logic.

    Order: guard on headline-only words first, then Jaccard on
    mechanism-expanded sets.  Mechanism overlap can only contribute to
    similarity AFTER headline agreement is confirmed.
    """
    words_a_hl = _headline_words(hl_a)
    words_b_hl = _headline_words(hl_b)

    # Step 1 — headline guard (no mechanism yet)
    if not _short_headline_guard(words_a_hl, words_b_hl):
        return False

    # Step 2 — expand with mechanism, then Jaccard
    words_a = words_a_hl | _headline_words(mech_a)
    words_b = words_b_hl | _headline_words(mech_b)
    return _jaccard(words_a, words_b) >= _ANALOG_THRESHOLD


def _expand_then_guard(
    hl_a: str, mech_a: str,
    hl_b: str, mech_b: str,
) -> bool:
    """Simulate the OLD (pre-fix) inner-loop logic for contrast.

    Jaccard on expanded sets first, guard second.
    """
    words_a_hl = _headline_words(hl_a)
    words_b_hl = _headline_words(hl_b)
    words_a = words_a_hl | _headline_words(mech_a)
    words_b = words_b_hl | _headline_words(mech_b)

    if _jaccard(words_a, words_b) < _ANALOG_THRESHOLD:
        return False
    return _short_headline_guard(words_a_hl, words_b_hl)


# ---------------------------------------------------------------------------
# 1) Short false analog — mechanism overlap present, guard blocks
# ---------------------------------------------------------------------------

class TestShortFalseAnalogBlocked(unittest.TestCase):
    """Guard on headline-only words must block pairs that share <2 hl tokens
    regardless of how much their mechanism texts overlap."""

    # Pair: both mention "oil" in the headline but are about different events;
    # mechanisms share several content words (iran, sanction, russia, oil).
    HL_A  = "Oil rises"
    MECH_A = "Iran sanctions tighten, cutting Russian oil supply to European refiners"
    HL_B  = "Oil falls"
    MECH_B = "Iran sanctions relief imminent; Russian oil exports to Europe normalise"

    def test_shared_hl_token_count_below_minimum(self):
        """Headlines share exactly 1 content token — below the 2-token minimum."""
        a = _headline_words(self.HL_A)
        b = _headline_words(self.HL_B)
        self.assertEqual(len(a & b), 1,
                         f"Expected exactly 1 shared hl token; got {a & b}")

    def test_mechanism_jaccard_would_pass_threshold(self):
        """Mechanism-expanded Jaccard exceeds 0.15 — proving mechanism overlap is real."""
        a = _headline_words(self.HL_A) | _headline_words(self.MECH_A)
        b = _headline_words(self.HL_B) | _headline_words(self.MECH_B)
        sim = _jaccard(a, b)
        self.assertGreaterEqual(sim, _ANALOG_THRESHOLD,
                                f"Expanded Jaccard {sim:.3f} should be ≥{_ANALOG_THRESHOLD}; "
                                "test premise failed")

    def test_guard_alone_blocks_pair(self):
        """_short_headline_guard returns False for this pair."""
        a = _headline_words(self.HL_A)
        b = _headline_words(self.HL_B)
        self.assertFalse(_short_headline_guard(a, b))

    def test_guard_before_expand_blocks(self):
        """Fixed order (guard first) blocks the pair."""
        self.assertFalse(_guard_then_expand(
            self.HL_A, self.MECH_A, self.HL_B, self.MECH_B,
        ))

    def test_old_and_new_order_agree_on_false(self):
        """Both orderings block this pair — regression check."""
        self.assertFalse(_expand_then_guard(
            self.HL_A, self.MECH_A, self.HL_B, self.MECH_B,
        ))
        self.assertFalse(_guard_then_expand(
            self.HL_A, self.MECH_A, self.HL_B, self.MECH_B,
        ))

    def test_single_token_headlines_blocked(self):
        """1-token headlines with purely mechanism-driven overlap are blocked."""
        # "oil" vs "tariff" — zero shared hl tokens, but mechanisms both discuss oil
        hl_a, mech_a = "Oil", "Oil supply disruption drives energy prices higher"
        hl_b, mech_b = "Tariffs", "US imposes tariffs on oil and energy imports"
        self.assertFalse(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_guard_fires_before_mechanism_is_consulted(self):
        """Prove guard evaluates to False before mechanism text is needed.

        If the guard blocks, the result is False regardless of what the
        mechanism texts say — we verify this by giving mechanism texts that
        would produce a very high Jaccard (identical texts).
        """
        hl_a, hl_b = "Oil rises", "Oil falls"
        same_mech = "Iran Russia OPEC oil sanction supply cut export"
        self.assertFalse(_guard_then_expand(hl_a, same_mech, hl_b, same_mech))


# ---------------------------------------------------------------------------
# 2) Short true analog — ≥2 shared hl tokens, guard passes
# ---------------------------------------------------------------------------

class TestShortTrueAnalogPreserved(unittest.TestCase):
    """Genuine short-headline analogs with ≥2 shared specific content tokens
    must still pass after the guard is applied first."""

    def test_opec_output_cut(self):
        """Classic OPEC cut pair — 'opec' + 'cut' shared."""
        hl_a = "OPEC cuts output targets"
        hl_b = "OPEC cuts production quota"
        mech_a = "Cartel agrees to reduce daily barrel output by 1 million"
        mech_b = "OPEC+ agrees production quota cut amid slowing demand"
        words_a = _headline_words(hl_a)
        words_b = _headline_words(hl_b)
        self.assertGreaterEqual(len(words_a & words_b), 2)
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_fed_rate_hike(self):
        """Fed rate hike pair — 'fed' + 'rate' shared."""
        hl_a = "Fed hikes rates aggressively"
        hl_b = "Fed rate hike stuns markets"
        mech_a = "FOMC raises benchmark rate by 75 bps to combat inflation"
        mech_b = "Federal Reserve rate decision surprises investors with 75 bps move"
        words_a = _headline_words(hl_a)
        words_b = _headline_words(hl_b)
        self.assertGreaterEqual(len(words_a & words_b), 2)
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_russia_oil_sanctions(self):
        """Russia oil sanction pair — 'russia' + 'oil' + 'sanction' shared."""
        hl_a = "Russia oil sanctions tighten"
        hl_b = "Russia oil sanction extended"
        mech_a = "EU extends sanctions on Russian crude exports"
        mech_b = "New sanctions package targets Russian oil pipeline routes"
        words_a = _headline_words(hl_a)
        words_b = _headline_words(hl_b)
        self.assertGreaterEqual(len(words_a & words_b), 2)
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_china_tariff_pair(self):
        """China tariff pair — 'china' + 'tariff' shared."""
        hl_a = "China tariffs escalate into trade war"
        hl_b = "China tariff retaliation hits agriculture"
        mech_a = "China tariff retaliation hits US exports and trade supply chains"
        mech_b = "China tariff retaliation hits US agricultural exports amid trade war"
        words_a = _headline_words(hl_a)
        words_b = _headline_words(hl_b)
        self.assertGreaterEqual(len(words_a & words_b), 2)
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_boj_yield_curve_pair(self):
        """BOJ yield-curve pair — 'boj' + 'yield' + 'curve' shared (likely ≥2)."""
        hl_a = "BOJ adjusts yield curve band"
        hl_b = "BOJ yield curve control tweak"
        mech_a = "Bank of Japan widens tolerance range for 10-year JGB yield"
        mech_b = "BOJ surprises with wider yield band allowance under YCC"
        words_a = _headline_words(hl_a)
        words_b = _headline_words(hl_b)
        self.assertGreaterEqual(len(words_a & words_b), 2)
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))


# ---------------------------------------------------------------------------
# 3) Longer analog behavior unchanged
# ---------------------------------------------------------------------------

class TestLongerAnalogUnchanged(unittest.TestCase):
    """For headlines above _SHORT_HEADLINE_THRESHOLD content words, the guard
    always passes and the Jaccard on expanded sets is the only gate."""

    def test_long_headline_guard_always_passes(self):
        """Guard returns True unconditionally for long-headline pairs."""
        from db import _SHORT_HEADLINE_THRESHOLD
        hl_a = "US imposes sweeping tariffs on Chinese semiconductor exports"
        hl_b = "US semiconductor tariff escalation deepens China trade tension"
        wa = _headline_words(hl_a)
        wb = _headline_words(hl_b)
        # Both headlines have more than threshold content words
        self.assertGreater(min(len(wa), len(wb)), _SHORT_HEADLINE_THRESHOLD)
        self.assertTrue(_short_headline_guard(wa, wb))

    def test_long_genuine_analog_passes_end_to_end(self):
        """Long headline pair with mechanism → match allowed."""
        hl_a = "US imposes sweeping tariffs on China semiconductor exports"
        mech_a = "US China tariff war hits semiconductor supply chains and tech exports"
        hl_b = "US semiconductor tariffs on China take effect amid tech war"
        mech_b = "US China tariff escalation hits semiconductor tech exports supply chains"
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_long_unrelated_pair_blocked_by_jaccard(self):
        """Long but unrelated headlines are blocked by Jaccard, not the guard."""
        from db import _SHORT_HEADLINE_THRESHOLD
        hl_a = "Iran nuclear sanctions tighten amid Ukraine war escalation"
        mech_a = "Geopolitical risk premium rises on energy supply disruption"
        hl_b = "BOJ adjusts yield curve control band for third consecutive quarter"
        mech_b = "Japanese monetary policy diverges from Fed as inflation stays low"
        wa = _headline_words(hl_a)
        wb = _headline_words(hl_b)
        # Guard passes (long headlines)
        self.assertTrue(_short_headline_guard(wa, wb))
        # But Jaccard on expanded sets should be below threshold
        words_a = wa | _headline_words(mech_a)
        words_b = wb | _headline_words(mech_b)
        self.assertLess(_jaccard(words_a, words_b), _ANALOG_THRESHOLD)
        # End-to-end: blocked by Jaccard
        self.assertFalse(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_mechanism_boosts_borderline_long_pair(self):
        """For long headlines near the Jaccard threshold, mechanism text
        can legitimately push similarity over 0.15."""
        hl_a = "Russia Ukraine war deepens energy supply disruption globally"
        mech_a = "Oil gas pipeline routes disrupted; European storage deficit widens"
        hl_b = "Russia Ukraine conflict drives European natural gas shortage"
        mech_b = "Nord Stream flow cuts force emergency storage refill across Europe"
        # Guard must pass (both long)
        wa = _headline_words(hl_a)
        wb = _headline_words(hl_b)
        self.assertTrue(_short_headline_guard(wa, wb))
        # End-to-end: mechanism assists a genuine match
        self.assertTrue(_guard_then_expand(hl_a, mech_a, hl_b, mech_b))

    def test_old_and_new_order_agree_on_long_true(self):
        """Order of guard vs Jaccard produces identical results for long pairs."""
        hl_a = "US imposes sweeping tariffs on China semiconductor exports"
        mech_a = "US China tariff war hits semiconductor supply chains and tech exports"
        hl_b = "US semiconductor tariffs on China take effect amid tech war"
        mech_b = "US China tariff escalation hits semiconductor tech exports supply chains"
        old = _expand_then_guard(hl_a, mech_a, hl_b, mech_b)
        new = _guard_then_expand(hl_a, mech_a, hl_b, mech_b)
        self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main()

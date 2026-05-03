"""
tests/test_ticker_overlap_dedupe.py

Focused tests for _dedupe_ticker_overlap in analyze_event.py.
No network calls, no API key needed.

Three invariant groups:
  1) Overlap removed / resolved — beneficiary wins
  2) Non-overlapping lists are unchanged
  3) Proxy-suffixed losers are exempt from dedupe
"""

import sys
import unittest

sys.path.insert(0, ".")
from analyze_event import _dedupe_ticker_overlap


# ---------------------------------------------------------------------------
# 1) Overlap removed / resolved
# ---------------------------------------------------------------------------

class TestOverlapRemoved(unittest.TestCase):

    def test_exact_match_removed_from_losers(self):
        """A ticker on both sides is dropped from losers."""
        bens, los = _dedupe_ticker_overlap(["GLD", "TLT"], ["USO", "GLD"])
        self.assertIn("GLD", bens)
        self.assertNotIn("GLD", los)
        self.assertIn("USO", los)

    def test_case_insensitive_dedup(self):
        """Case difference does not prevent dedup."""
        bens, los = _dedupe_ticker_overlap(["GLD"], ["gld", "USO"])
        self.assertNotIn("gld", los)
        self.assertIn("USO", los)

    def test_beneficiaries_list_unchanged(self):
        """_dedupe_ticker_overlap never modifies the beneficiary list."""
        bens, los = _dedupe_ticker_overlap(["GLD", "SLV"], ["GLD", "SLV"])
        self.assertEqual(bens, ["GLD", "SLV"])

    def test_full_overlap_empties_losers(self):
        """All-overlap losers list becomes empty."""
        bens, los = _dedupe_ticker_overlap(["GLD", "TLT"], ["GLD", "TLT"])
        self.assertEqual(los, [])

    def test_multiple_overlapping_removed(self):
        """Several overlapping tickers are all removed from losers."""
        bens, los = _dedupe_ticker_overlap(
            ["GLD", "TLT", "SLV"],
            ["GLD", "USO", "TLT", "XOM"],
        )
        for t in ("GLD", "TLT"):
            self.assertNotIn(t, los)
        for t in ("USO", "XOM"):
            self.assertIn(t, los)

    def test_return_type_is_tuple_of_lists(self):
        bens, los = _dedupe_ticker_overlap(["GLD"], ["GLD", "USO"])
        self.assertIsInstance(bens, list)
        self.assertIsInstance(los, list)


# ---------------------------------------------------------------------------
# 2) Non-overlapping lists are unchanged
# ---------------------------------------------------------------------------

class TestNonOverlapUnchanged(unittest.TestCase):

    def test_disjoint_lists_pass_through(self):
        bens, los = _dedupe_ticker_overlap(["GLD", "TLT"], ["USO", "XLE"])
        self.assertEqual(bens, ["GLD", "TLT"])
        self.assertEqual(los, ["USO", "XLE"])

    def test_empty_losers_unchanged(self):
        bens, los = _dedupe_ticker_overlap(["GLD"], [])
        self.assertEqual(bens, ["GLD"])
        self.assertEqual(los, [])

    def test_empty_beneficiaries_unchanged(self):
        bens, los = _dedupe_ticker_overlap([], ["USO", "XLE"])
        self.assertEqual(bens, [])
        self.assertEqual(los, ["USO", "XLE"])

    def test_both_empty(self):
        bens, los = _dedupe_ticker_overlap([], [])
        self.assertEqual(bens, [])
        self.assertEqual(los, [])

    def test_order_preserved_in_losers(self):
        """Non-overlapping losers retain their original order."""
        bens, los = _dedupe_ticker_overlap(["GLD"], ["XOM", "USO", "XLE"])
        self.assertEqual(los, ["XOM", "USO", "XLE"])


# ---------------------------------------------------------------------------
# 3) Proxy-suffixed losers are exempt
# ---------------------------------------------------------------------------

class TestProxySuffixExempt(unittest.TestCase):

    def test_proxy_loser_kept_despite_overlap(self):
        """A loser marked '(proxy)' survives even if its ticker appears in bens."""
        bens, los = _dedupe_ticker_overlap(
            ["GLD"],
            ["GLD (proxy)", "USO"],
        )
        self.assertIn("GLD (proxy)", los)
        self.assertIn("USO", los)

    def test_plain_loser_still_removed_alongside_proxy(self):
        """Plain overlapping loser is removed even when a proxy version is kept."""
        bens, los = _dedupe_ticker_overlap(
            ["GLD"],
            ["GLD", "GLD (proxy)"],
        )
        self.assertNotIn("GLD", los)
        self.assertIn("GLD (proxy)", los)

    def test_proxy_case_insensitive(self):
        """(Proxy) with capital P is still treated as exempt."""
        bens, los = _dedupe_ticker_overlap(
            ["TLT"],
            ["TLT (Proxy)"],
        )
        self.assertIn("TLT (Proxy)", los)

    def test_non_proxy_suffix_not_exempt(self):
        """A different parenthetical suffix does not grant proxy exemption."""
        bens, los = _dedupe_ticker_overlap(
            ["GLD"],
            ["GLD (inverse)"],
        )
        self.assertNotIn("GLD (inverse)", los)

    def test_proxy_non_overlapping_kept(self):
        """A proxy loser with no overlap is still kept."""
        bens, los = _dedupe_ticker_overlap(
            ["GLD"],
            ["USO (proxy)"],
        )
        self.assertIn("USO (proxy)", los)


if __name__ == "__main__":
    unittest.main()

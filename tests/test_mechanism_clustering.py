"""
tests/test_mechanism_clustering.py

Unit tests for the mechanism conflict guard added to news_clustering.py.
Covers _extract_mechanism, _mechanisms_conflict, threshold validation,
and end-to-end cluster separation.
"""

import sys
import unittest

sys.path.insert(0, ".")
from news_clustering import (
    _extract_mechanism,
    _mechanisms_conflict,
    _MECHANISM_OVERRIDE_THRESHOLD,
    _CLUSTER_THRESHOLD,
    _cosine_sim,
    _build_tfidf_vectors,
    cluster_headlines,
)


class TestExtractMechanism(unittest.TestCase):

    def test_tariffs_semiconductors(self):
        action, sector = _extract_mechanism("US imposes tariffs on Chinese semiconductors")
        self.assertEqual(action, "tariffs")
        self.assertEqual(sector, "semiconductors")

    def test_sanctions_tech(self):
        action, sector = _extract_mechanism("US moves to sanction Chinese technology companies")
        self.assertEqual(action, "sanctions")
        self.assertEqual(sector, "unknown")

    def test_monetary_policy(self):
        action, _ = _extract_mechanism("Fed raises interest rate by 25bp")
        self.assertEqual(action, "monetary policy")

    def test_unknown_action(self):
        action, _ = _extract_mechanism("Markets open higher on Tuesday")
        self.assertEqual(action, "unknown")

    def test_unknown_sector(self):
        _, sector = _extract_mechanism("US imposes tariffs on goods")
        self.assertEqual(sector, "unknown")

    def test_energy_sector(self):
        _, sector = _extract_mechanism("OPEC cuts oil production")
        self.assertEqual(sector, "energy")


class TestMechanismsConflict(unittest.TestCase):

    def test_tariffs_vs_sanctions_conflict(self):
        self.assertTrue(_mechanisms_conflict(
            ("tariffs", "semiconductors"),
            ("sanctions", "semiconductors"),
        ))

    def test_tariffs_vs_trade_policy_no_conflict(self):
        # Related pair — should NOT block
        self.assertFalse(_mechanisms_conflict(
            ("tariffs", "energy"),
            ("trade policy", "energy"),
        ))

    def test_sanctions_vs_export_restrictions_no_conflict(self):
        # Related pair — should NOT block
        self.assertFalse(_mechanisms_conflict(
            ("sanctions", "semiconductors"),
            ("export restrictions", "semiconductors"),
        ))

    def test_same_action_no_conflict(self):
        self.assertFalse(_mechanisms_conflict(
            ("tariffs", "energy"),
            ("tariffs", "semiconductors"),
        ))

    def test_unknown_action_a_no_conflict(self):
        self.assertFalse(_mechanisms_conflict(
            ("unknown", "energy"),
            ("sanctions", "energy"),
        ))

    def test_unknown_action_b_no_conflict(self):
        self.assertFalse(_mechanisms_conflict(
            ("tariffs", "energy"),
            ("unknown", "energy"),
        ))

    def test_monetary_vs_tariffs_conflict(self):
        self.assertTrue(_mechanisms_conflict(
            ("monetary policy", "finance"),
            ("tariffs", "energy"),
        ))

    def test_fiscal_vs_military_conflict(self):
        self.assertTrue(_mechanisms_conflict(
            ("fiscal policy", "unknown"),
            ("military action", "unknown"),
        ))


class TestThresholdValidation(unittest.TestCase):
    """Validate that the guard-relevant headline pair produces cosine in [_CLUSTER_THRESHOLD, _MECHANISM_OVERRIDE_THRESHOLD)."""

    TITLE_A = "US imposes tariffs on Chinese semiconductors"
    TITLE_B = "US moves to sanction Chinese technology companies"

    def _cosine_of_pair(self, a: str, b: str) -> float:
        vecs, _ = _build_tfidf_vectors([a, b])
        return _cosine_sim(vecs[0], vecs[1])

    def test_pair_cosine_in_guard_range(self):
        """Cosine must be >= _CLUSTER_THRESHOLD (triggers guard) and < _MECHANISM_OVERRIDE_THRESHOLD (not overridden)."""
        cos = self._cosine_of_pair(self.TITLE_A, self.TITLE_B)
        self.assertGreaterEqual(
            cos, _CLUSTER_THRESHOLD,
            f"Cosine {cos:.4f} below cluster threshold — guard would never fire",
        )
        self.assertLess(
            cos, _MECHANISM_OVERRIDE_THRESHOLD,
            f"Cosine {cos:.4f} at or above override threshold — guard would not block",
        )

    def test_near_duplicate_above_override_threshold(self):
        """Near-duplicate pair must be >= _MECHANISM_OVERRIDE_THRESHOLD so it still merges."""
        a = "US imposes tariffs on Chinese semiconductors"
        b = "US imposes new tariffs on Chinese semiconductor imports"
        cos = self._cosine_of_pair(a, b)
        self.assertGreaterEqual(
            cos, _MECHANISM_OVERRIDE_THRESHOLD,
            f"Cosine {cos:.4f} below override threshold — near-duplicates would be wrongly blocked",
        )


class TestEndToEndClusterSeparation(unittest.TestCase):

    def _make_record(self, title: str, source: str = "Reuters") -> dict:
        return {
            "title": title,
            "source": source,
            "published_at": "2026-04-15T10:00:00",
            "url": "",
            "summary": "",
        }

    def test_tariffs_vs_sanctions_produces_two_clusters(self):
        """Tariff headline and sanction headline with conflicting mechanisms must not merge."""
        records = [
            self._make_record("US imposes tariffs on Chinese semiconductors"),
            self._make_record("US moves to sanction Chinese technology companies"),
        ]
        clusters = cluster_headlines(records)
        self.assertEqual(
            len(clusters), 2,
            "Expected 2 separate clusters but got 1 — mechanism guard not blocking",
        )

    def test_related_actions_still_merge(self):
        """Tariff and trade-policy headlines are compatible and should still merge."""
        records = [
            self._make_record("US imposes tariffs on Chinese goods"),
            self._make_record("US trade policy shifts on Chinese imports"),
        ]
        clusters = cluster_headlines(records)
        # If they share enough cosine AND are related actions, they should merge.
        # We check that the guard does NOT prevent a valid merge here.
        # (If cosine happens to be below threshold, this test still passes — it just
        # means the headlines are too different to merge regardless of mechanism.)
        if len(clusters) == 1:
            self.assertEqual(len(clusters), 1)
        else:
            # Ensure they were NOT blocked by mechanism — both should be in separate
            # clusters only if cosine was below threshold, not due to mechanism block.
            vecs, _ = _build_tfidf_vectors([r["title"] for r in records])
            cos = _cosine_sim(vecs[0], vecs[1])
            self.assertLess(
                cos, _CLUSTER_THRESHOLD,
                f"Cosine {cos:.4f} is above threshold but related-action headlines were not merged — mechanism guard wrongly blocked",
            )

    def test_same_mechanism_still_merges(self):
        """Two tariff headlines should merge normally."""
        records = [
            self._make_record("US imposes tariffs on Chinese goods"),
            self._make_record("US announces tariffs on Chinese products"),
        ]
        clusters = cluster_headlines(records)
        self.assertEqual(len(clusters), 1)


if __name__ == "__main__":
    unittest.main()

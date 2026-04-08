"""
tests/test_eval_quality.py

Focused tests for the quality-scoring helper used by the eval pass.
No API calls — pure scoring over synthetic analysis dicts.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval import _quality_score, QUALITY_CHECKS  # noqa: E402


def _rich() -> dict:
    """A baseline analysis that should score a perfect 10/10."""
    return {
        "what_changed": "The US Commerce Department added 28 Chinese semiconductor firms to the Entity List.",
        "mechanism_summary": (
            "Chinese fabs lose access to ASML EUV lithography, Lam Research etch, "
            "and Applied Materials deposition equipment. Non-Chinese fabs gain "
            "pricing power as capacity at leading nodes becomes scarce."
        ),
        "beneficiaries": ["TSMC", "Samsung Foundry"],
        "losers": ["CXMT", "YMTC"],
        "beneficiary_tickers": ["TSM", "SMH"],
        "loser_tickers": ["LRCX", "AMAT"],
        "transmission_chain": [
            "28 Chinese semiconductor firms added to the Entity List",
            "Cuts access to EUV lithography, etch, and deposition equipment",
            "Non-Chinese fabs gain pricing power at leading nodes",
            "TSMC benefits; LRCX and AMAT lose China revenue",
        ],
        "if_persists": {"horizon": "quarters"},
        "currency_channel": {
            "pair": "USD/CNY",
            "mechanism": "Weaker CNY reflects semiconductor import friction.",
        },
        "confidence": "high",
    }


class TestQualityScore(unittest.TestCase):

    def test_rich_analysis_scores_full_marks(self):
        r = _quality_score(_rich())
        self.assertEqual(r["score"], len(QUALITY_CHECKS))
        self.assertEqual(r["max_score"], len(QUALITY_CHECKS))
        self.assertTrue(all(r["breakdown"].values()))

    def test_short_mechanism_loses_points(self):
        a = _rich()
        a["mechanism_summary"] = "Too short."
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["mechanism_length_ok"])
        self.assertLess(r["score"], len(QUALITY_CHECKS))

    def test_insufficient_evidence_mechanism_fails(self):
        a = _rich()
        a["mechanism_summary"] = "Insufficient evidence to identify mechanism."
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["mechanism_length_ok"])

    def test_short_transmission_chain_loses_point(self):
        a = _rich()
        a["transmission_chain"] = ["only", "two"]
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["transmission_chain_depth_ok"])

    def test_missing_beneficiary_tickers_loses_point(self):
        a = _rich()
        a["beneficiary_tickers"] = ["TSM"]  # only one — needs ≥ 2
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["beneficiary_tickers_ok"])

    def test_missing_loser_tickers_loses_point(self):
        a = _rich()
        a["loser_tickers"] = []
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["loser_tickers_ok"])

    def test_degraded_flag_loses_point(self):
        a = _rich()
        a["degraded"] = True
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["not_degraded"])

    def test_validation_warnings_lose_point(self):
        a = _rich()
        a["validation_warnings"] = ["confidence downgraded from high to medium"]
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["no_validation_warnings"])

    def test_vague_what_changed_loses_point(self):
        a = _rich()
        a["what_changed"] = "Various companies saw multiple changes in the market today."
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["specific_what_changed"])

    def test_missing_horizon_loses_point(self):
        a = _rich()
        a["if_persists"] = {}
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["if_persists_horizon_ok"])

    def test_currency_channel_null_both_counts_complete(self):
        # Model correctly declared no FX channel → still counts as complete.
        a = _rich()
        a["currency_channel"] = {"pair": None, "mechanism": None}
        r = _quality_score(a)
        self.assertTrue(r["breakdown"]["currency_channel_complete"])

    def test_currency_channel_half_populated_fails(self):
        a = _rich()
        a["currency_channel"] = {"pair": "USD/CNY", "mechanism": None}
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["currency_channel_complete"])

    def test_empty_entities_fails_populated_check(self):
        a = _rich()
        a["beneficiaries"] = []
        a["losers"] = []
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["both_entities_populated"])

    def test_weak_analysis_scores_low(self):
        weak = {
            "what_changed": "short",
            "mechanism_summary": "Insufficient evidence.",
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "transmission_chain": [],
            "if_persists": {},
            "currency_channel": {},
            "degraded": True,
            "validation_warnings": ["thin analysis"],
        }
        r = _quality_score(weak)
        # Only currency_channel_complete (both-null path) should pass.
        self.assertLessEqual(r["score"], 2)


if __name__ == "__main__":
    unittest.main()

"""
tests/test_asset_eligibility.py

Contract tests for the per-asset eligibility + proxy-confidence layer.

Covers:
  1. ``compute_eligibility`` — tier anchoring, name-mention bump,
     position decay, confidence-band mapping.
  2. ``classify_and_rank_assets`` trim — eligibility fields are on
     every emitted entry.
  3. ``compute_validation_plan`` — the score + confidence flow through
     onto primary / secondary / signal asset rows, and the excluded
     list is surfaced with a reason for every dropped ticker.
  4. Primary bucket sharpness — direct-name beneficiaries rank above
     sector ETFs and satellite names within the primary bucket.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from asset_selection import (
    compute_eligibility,
    classify_and_rank_assets,
)
from validation_plan import compute_validation_plan


# ---------------------------------------------------------------------------
# 1. compute_eligibility primitive
# ---------------------------------------------------------------------------

class TestComputeEligibility(unittest.TestCase):

    def test_direct_proxy_scores_highest(self):
        e = compute_eligibility({"tier": "direct_proxy", "list_index": 0})
        self.assertGreaterEqual(e["score"], 0.85)
        self.assertEqual(e["confidence"], "high")

    def test_sector_proxy_scores_between_direct_and_second_order(self):
        direct = compute_eligibility({"tier": "direct_proxy",
                                       "list_index": 0})["score"]
        sector = compute_eligibility({"tier": "sector_proxy",
                                       "list_index": 0})["score"]
        second = compute_eligibility({"tier": "second_order",
                                       "list_index": 0})["score"]
        self.assertGreater(direct, sector)
        self.assertGreater(sector, second)

    def test_hedge_signal_is_low_confidence(self):
        e = compute_eligibility({"tier": "hedge_signal", "list_index": 0})
        self.assertEqual(e["confidence"], "low")

    def test_excluded_tier_scores_zero(self):
        e = compute_eligibility({"tier": "excluded", "list_index": 0})
        self.assertEqual(e["score"], 0.0)
        self.assertEqual(e["confidence"], "excluded")

    def test_name_mentioned_bumps_score(self):
        base  = compute_eligibility({"tier": "direct_proxy",
                                      "list_index": 0})["score"]
        named = compute_eligibility({"tier": "direct_proxy",
                                      "list_index": 0,
                                      "name_mentioned": True})["score"]
        self.assertGreater(named, base)

    def test_position_decay_penalises_later_picks(self):
        first  = compute_eligibility({"tier": "direct_proxy",
                                       "list_index": 0})["score"]
        fourth = compute_eligibility({"tier": "direct_proxy",
                                       "list_index": 3})["score"]
        self.assertGreater(first, fourth)

    def test_position_decay_is_capped(self):
        """A very late-position direct proxy still ranks above a
        second-order first-pick — the position decay cannot reverse
        the tier ordering."""
        late_direct = compute_eligibility({"tier": "direct_proxy",
                                            "list_index": 10})["score"]
        first_second = compute_eligibility({"tier": "second_order",
                                             "list_index": 0})["score"]
        self.assertGreater(late_direct, first_second)

    def test_score_is_bounded_in_unit_interval(self):
        for tier in ("direct_proxy", "sector_proxy", "second_order",
                     "hedge_signal", "excluded"):
            for idx in (0, 1, 5, 20):
                e = compute_eligibility({
                    "tier": tier, "list_index": idx,
                    "name_mentioned": True,
                })
                self.assertGreaterEqual(e["score"], 0.0)
                self.assertLessEqual(e["score"], 1.0)


# ---------------------------------------------------------------------------
# 2. Classification trim carries the eligibility fields
# ---------------------------------------------------------------------------

class TestClassificationEmitsEligibility(unittest.TestCase):

    def test_primary_entries_carry_score_and_confidence(self):
        classified = classify_and_rank_assets(
            beneficiary_tickers=["CVX", "XOM"],
            beneficiaries_text=["Chevron (CVX)", "Exxon (XOM)"],
            mechanism_family="supply_shock",
        )
        for entry in classified["primary"]["beneficiary"]:
            self.assertIn("eligibility_score", entry)
            self.assertIn("proxy_confidence", entry)
            self.assertGreaterEqual(entry["eligibility_score"], 0.0)

    def test_hedge_signal_entries_carry_eligibility(self):
        classified = classify_and_rank_assets(
            loser_tickers=["VXX"],
            mechanism_family="supply_shock",
        )
        self.assertEqual(len(classified["hedge_signal"]), 1)
        row = classified["hedge_signal"][0]
        self.assertIn("eligibility_score", row)
        self.assertEqual(row["proxy_confidence"], "low")


# ---------------------------------------------------------------------------
# 3. Plan integration — eligibility + excluded_assets on the plan
# ---------------------------------------------------------------------------

class TestValidationPlanEligibility(unittest.TestCase):

    def test_every_asset_row_carries_eligibility_fields(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX", "USO"],
            beneficiaries_text=["Chevron (CVX)"],
            loser_tickers=["VXX"],
        )
        for bucket in ("primary_assets", "secondary_assets", "signal_assets"):
            for row in plan.get(bucket, []):
                self.assertIn("eligibility_score", row,
                              f"missing score on {bucket}")
                self.assertIn("proxy_confidence", row,
                              f"missing confidence on {bucket}")

    def test_direct_beneficiary_ranks_higher_than_sector_etf(self):
        """Strict role separation: direct names land in primary,
        ETFs land in secondary regardless of channel.  CVX's
        primary-tier eligibility score outranks USO's secondary-tier
        score across the bucket boundary."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["USO", "CVX"],  # ETF before direct name
            beneficiaries_text=["Chevron (CVX)"],
        )
        score_by_sym: dict[str, float] = {}
        for bucket in ("primary_assets", "secondary_assets"):
            for r in plan.get(bucket, []):
                score_by_sym[r["symbol"]] = r["eligibility_score"]
        self.assertGreater(
            score_by_sym["CVX"], score_by_sym["USO"],
            f"direct name must outrank sector ETF: {score_by_sym}",
        )
        # Bucket placement matches the role-separation rule.
        self.assertIn(
            "CVX", [a["symbol"] for a in plan["primary_assets"]],
        )
        self.assertIn(
            "USO", [a["symbol"] for a in plan["secondary_assets"]],
        )

    def test_excluded_assets_surface_with_reason(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["SPY", "CVX"],  # SPY is broad-market → excluded
            beneficiaries_text=["Chevron (CVX)"],
        )
        excluded = plan["excluded_assets"]
        self.assertTrue(excluded, "SPY should have been excluded")
        spy_entry = next((e for e in excluded if e["symbol"] == "SPY"), None)
        self.assertIsNotNone(spy_entry)
        self.assertTrue(spy_entry["reason"], "excluded entry must carry a reason")

    def test_excluded_assets_empty_when_all_tickers_clean(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX"],
        )
        self.assertEqual(plan["excluded_assets"], [])


# ---------------------------------------------------------------------------
# 4. Primary bucket sharpness — the whole point of this task
# ---------------------------------------------------------------------------

class TestPrimaryBucketSharpness(unittest.TestCase):

    def test_named_direct_proxy_outranks_unnamed_direct_proxy(self):
        """The LLM explicitly mentioned CVX in beneficiaries text; XOM
        it only listed as a ticker.  Both are direct — but the named
        one must rank higher so the primary bucket surfaces the
        stronger validation target first."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX", "XOM"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        primary = plan["primary_assets"]
        score_by_sym = {r["symbol"]: r["eligibility_score"] for r in primary}
        self.assertGreater(score_by_sym["CVX"], score_by_sym["XOM"])

    def test_confidence_labels_track_score(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX"],
            beneficiaries_text=["Chevron (CVX)"],
            loser_tickers=["VXX"],
        )
        primary = plan["primary_assets"][0]
        signal  = plan["signal_assets"][0]
        # high for a named direct proxy; low for a hedge/signal.
        self.assertEqual(primary["proxy_confidence"], "high")
        self.assertEqual(signal["proxy_confidence"], "low")


class TestEligibilityComponents(unittest.TestCase):
    """Four-component eligibility scoring exposes direct_exposure /
    liquidity / channel_match / noise_risk on every asset row, plus a
    short rationale.  Excluded entries also carry the rationale."""

    def _components(self, plan: dict, sym: str, bucket: str) -> dict:
        for row in plan.get(bucket, []):
            if row.get("symbol") == sym:
                return row
        raise AssertionError(
            f"{sym} not found in {bucket}: "
            f"{[r.get('symbol') for r in plan.get(bucket, [])]}"
        )

    def test_direct_name_high_direct_exposure_low_noise(self):
        """A direct single-name pick (CVX) named in the thesis carries
        the maximum direct_exposure (1.0) and the lowest noise_risk."""
        plan = compute_validation_plan(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["CVX"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        row = self._components(plan, "CVX", "primary_assets")
        comps = row["eligibility_components"]
        self.assertEqual(comps["direct_exposure"], 1.0)
        self.assertLess(comps["noise_risk"], 0.30)
        # On a primary-pack channel (commodities → equities is in pack
        # via secondary; CVX defaults to equities which is in supply
        # pack).  Match score should be material.
        self.assertGreater(comps["channel_match"], 0.5)
        self.assertEqual(comps["liquidity"], 1.0)

    def test_sector_etf_medium_components(self):
        """A sector ETF (XLE) on its family channel scores
        meaningfully on direct_exposure and channel_match but lower
        than a direct name on both."""
        plan = compute_validation_plan(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["XLE"],
        )
        row = self._components(plan, "XLE", "secondary_assets")
        comps = row["eligibility_components"]
        # ETFs are indirect — direct_exposure capped well below 1.0.
        self.assertLess(comps["direct_exposure"], 0.7)
        self.assertGreaterEqual(comps["direct_exposure"], 0.4)
        # Equities IS in commodity_squeeze's pack, so channel match
        # should clear the kept-asset floor.
        self.assertGreater(comps["channel_match"], 0.5)

    def test_broad_market_index_high_noise_rejected(self):
        """SPY is a broad-market index — high noise_risk ≥ 0.95 and
        the row lands in excluded_assets with a rationale."""
        plan = compute_validation_plan(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["SPY"],
        )
        row = self._components(plan, "SPY", "excluded_assets")
        self.assertEqual(row["eligibility_status"], "rejected")
        self.assertIn("eligibility_rationale", row)
        self.assertTrue(
            isinstance(row["eligibility_rationale"], str)
            and row["eligibility_rationale"].strip(),
        )

    def test_off_pack_etf_low_channel_match(self):
        """CPER is a commodities ETF; fiscal_issuance pack covers
        rates / fx / credit / equities.  channel_match collapses to
        0.0 and the row is rejected."""
        plan = compute_validation_plan(
            mechanism_family="fiscal_issuance",
            beneficiary_tickers=["CPER"],
        )
        # CPER lands in excluded_assets; check its rationale.
        row = self._components(plan, "CPER", "excluded_assets")
        self.assertIn("eligibility_rationale", row)
        rationale = row["eligibility_rationale"]
        self.assertIn("CPER", rationale)

    def test_every_kept_asset_carries_components_dict(self):
        """Contract: every primary / secondary / signal asset row
        carries an ``eligibility_components`` dict with the four
        canonical axes."""
        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            beneficiary_tickers=["KRE", "VXX"],
        )
        for bucket in ("primary_assets", "secondary_assets", "signal_assets"):
            for row in plan[bucket]:
                self.assertIn(
                    "eligibility_components", row,
                    f"{bucket} row missing components: {row}",
                )
                comps = row["eligibility_components"]
                self.assertEqual(
                    set(comps.keys()),
                    {"direct_exposure", "liquidity",
                     "channel_match", "noise_risk"},
                )
                for axis, val in comps.items():
                    self.assertGreaterEqual(val, 0.0)
                    self.assertLessEqual(val, 1.0)
                self.assertIn("eligibility_rationale", row)
                self.assertTrue(row["eligibility_rationale"].strip())

    def test_excluded_assets_carry_eligibility_rationale(self):
        """Every entry in excluded_assets — whether rejected by
        asset_selection (broad/foreign) or by validation_plan
        (off-pack/duplicate/signal-misuse) — carries an
        eligibility_rationale string."""
        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            beneficiary_tickers=["SPY", "VXX", "CPER"],  # broad / signal misuse / off-pack
        )
        self.assertGreater(len(plan["excluded_assets"]), 0)
        for row in plan["excluded_assets"]:
            self.assertIn(
                "eligibility_rationale", row,
                f"excluded row missing rationale: {row}",
            )


if __name__ == "__main__":
    unittest.main()

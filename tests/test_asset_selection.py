"""
tests/test_asset_selection.py

Contract tests for the post-LLM asset-selection discipline.

Covers:
  1. Tier classification — single names → direct_proxy, sector ETFs →
     sector_proxy (when on the family's primary channel) or second_order
     (otherwise), inverse/vol/FX → hedge_signal, broad indices /
     price benchmarks / foreign listings → excluded.
  2. Name-mention boost — a symbol that appears as a whole token in
     the beneficiaries/losers text ranks above list-position peers.
  3. Cleaned output lists — the downstream market_check never sees
     excluded or hedge-only tickers.
  4. Mechanism-family awareness — the same commodity ETF is promoted
     to sector_proxy on a commodity-family shock and demoted to
     second_order on a policy_surprise.
  5. Defensive behaviour — None / empty / non-string inputs never
     raise; collisions across sides are reported as excluded.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_selection import (
    TIER_ORDER,
    classify_and_rank_assets,
)


def _tiers(side: list[dict]) -> dict[str, str]:
    return {e["symbol"]: e["tier"] for e in side}


# ---------------------------------------------------------------------------
# 1. Tier classification
# ---------------------------------------------------------------------------

class TestTierClassification(unittest.TestCase):

    def test_tier_order_is_canonical(self):
        self.assertEqual(
            TIER_ORDER,
            (
                "direct_proxy", "sector_proxy", "second_order",
                "hedge_signal", "excluded",
            ),
        )

    def test_single_name_is_direct_proxy(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["XOM", "CVX"],
            mechanism_family="supply_shock",
        )
        symbols = _tiers(r["primary"]["beneficiary"])
        self.assertEqual(symbols["XOM"], "direct_proxy")
        self.assertEqual(symbols["CVX"], "direct_proxy")

    def test_sector_etf_on_primary_channel_is_sector_proxy(self):
        # supply_shock → primary channels include "commodities";
        # XLE is an equities-channel ETF, not commodities — so this
        # is testing the equities match.  supply_shock's pack includes
        # "equities" in first too, so XLE lands in sector_proxy.
        r = classify_and_rank_assets(
            beneficiary_tickers=["XLE"],
            mechanism_family="supply_shock",
        )
        symbols = _tiers(r["primary"]["beneficiary"])
        self.assertEqual(symbols["XLE"], "sector_proxy")

    def test_commodity_etf_on_commodity_family_is_sector_proxy(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["USO"],
            mechanism_family="commodity_squeeze",
        )
        symbols = _tiers(r["primary"]["beneficiary"])
        self.assertEqual(symbols["USO"], "sector_proxy")

    def test_inverse_etf_is_hedge_signal(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["SQQQ"],
            mechanism_family="policy_surprise",
        )
        hedge_symbols = {e["symbol"] for e in r["hedge_signal"]}
        self.assertIn("SQQQ", hedge_symbols)
        # And the cleaned list drops it.
        self.assertNotIn("SQQQ", r["cleaned_beneficiary_tickers"])

    def test_vol_etf_is_hedge_signal(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["VXX", "UVXY"],
            mechanism_family="bank_stress",
        )
        hedge_symbols = {e["symbol"] for e in r["hedge_signal"]}
        self.assertIn("VXX", hedge_symbols)
        self.assertIn("UVXY", hedge_symbols)

    def test_fx_etf_is_hedge_signal(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["UUP", "FXE"],
            mechanism_family="policy_surprise",
        )
        hedge_symbols = {e["symbol"] for e in r["hedge_signal"]}
        self.assertIn("UUP", hedge_symbols)
        self.assertIn("FXE", hedge_symbols)

    def test_broad_index_is_excluded(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["SPY", "QQQ", "IWM", "VTI"],
            mechanism_family="supply_shock",
        )
        excluded = {e["symbol"] for e in r["excluded"]}
        for s in ("SPY", "QQQ", "IWM", "VTI"):
            self.assertIn(s, excluded)
        self.assertEqual(r["cleaned_beneficiary_tickers"], [])

    def test_benchmark_symbol_is_excluded(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["^VIX", "DXY", "WTI"],
        )
        excluded = {e["symbol"] for e in r["excluded"]}
        self.assertEqual(excluded, {"^VIX", "DXY", "WTI"})

    def test_foreign_listing_is_excluded(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["7203.T", "NESN.L", "SHOP.TO"],
        )
        excluded = {e["symbol"] for e in r["excluded"]}
        self.assertEqual(len(excluded), 3)


# ---------------------------------------------------------------------------
# 2. Name-mention boost
# ---------------------------------------------------------------------------

class TestNameMentionBoost(unittest.TestCase):

    def test_named_ticker_ranks_above_list_neighbour(self):
        """XOM appears second in the LLM list but is named in
        beneficiaries text; must be emitted first within its tier."""
        r = classify_and_rank_assets(
            beneficiary_tickers=["CVX", "XOM"],
            beneficiaries_text=["Exxon (XOM) global upstream"],
            mechanism_family="supply_shock",
        )
        top = [e["symbol"] for e in r["primary"]["beneficiary"]]
        self.assertEqual(top[0], "XOM")
        self.assertEqual(top[1], "CVX")

    def test_unmentioned_ticker_holds_list_order(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["CVX", "XOM"],
            beneficiaries_text=["Energy majors benefit broadly"],
            mechanism_family="supply_shock",
        )
        top = [e["symbol"] for e in r["primary"]["beneficiary"]]
        self.assertEqual(top, ["CVX", "XOM"])

    def test_mention_flag_is_set(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["XOM"],
            beneficiaries_text=["Exxon (XOM) global upstream"],
        )
        entry = r["primary"]["beneficiary"][0]
        self.assertTrue(entry["name_mentioned"])


# ---------------------------------------------------------------------------
# 3. Cleaned lists downstream
# ---------------------------------------------------------------------------

class TestCleanedLists(unittest.TestCase):

    def test_cleaned_list_excludes_broad_index_and_hedge(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["XOM", "SPY", "VXX", "XLE"],
            mechanism_family="supply_shock",
        )
        # SPY + VXX dropped (excluded + hedge_signal respectively).
        # XOM + XLE survive.
        cleaned = set(r["cleaned_beneficiary_tickers"])
        self.assertEqual(cleaned, {"XOM", "XLE"})

    def test_secondary_tier_still_ships_to_market_check(self):
        """An ETF on a non-primary channel is 'second_order' but still
        useful as corroboration — must ship to market_check.  Uses a
        family whose primary pack does NOT include equities."""
        r = classify_and_rank_assets(
            beneficiary_tickers=["XLU"],          # equities-channel ETF
            mechanism_family="fiscal_issuance",   # primary pack = rates + fx
        )
        self.assertIn("XLU", r["cleaned_beneficiary_tickers"])
        tiers = _tiers(r["secondary"]["beneficiary"])
        self.assertEqual(tiers["XLU"], "second_order")

    def test_collision_across_sides_rejected(self):
        """A ticker on both lists is dropped from loser side + reported."""
        r = classify_and_rank_assets(
            beneficiary_tickers=["XOM"],
            loser_tickers=["XOM", "AAL"],
        )
        self.assertIn("XOM", r["cleaned_beneficiary_tickers"])
        self.assertNotIn("XOM", r["cleaned_loser_tickers"])
        self.assertIn("AAL", r["cleaned_loser_tickers"])
        excluded_symbols = {e["symbol"] for e in r["excluded"]}
        self.assertIn("XOM", excluded_symbols)


# ---------------------------------------------------------------------------
# 4. Mechanism-family awareness
# ---------------------------------------------------------------------------

class TestFamilyAwareness(unittest.TestCase):

    def test_commodity_etf_is_sector_proxy_on_commodity_shock(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["USO"],
            mechanism_family="commodity_squeeze",
        )
        tiers = _tiers(r["primary"]["beneficiary"])
        self.assertEqual(tiers["USO"], "sector_proxy")

    def test_commodity_etf_is_second_order_on_policy_surprise(self):
        # policy_surprise first-pack = rates / fx / vol — NO commodities.
        r = classify_and_rank_assets(
            beneficiary_tickers=["USO"],
            mechanism_family="policy_surprise",
        )
        tiers = _tiers(r["secondary"]["beneficiary"])
        self.assertEqual(tiers["USO"], "second_order")

    def test_bond_etf_is_sector_proxy_on_fiscal_issuance(self):
        # fiscal_issuance primary-pack = rates + fx; TLT is rates-channel.
        r = classify_and_rank_assets(
            beneficiary_tickers=["TLT"],
            mechanism_family="fiscal_issuance",
        )
        tiers = _tiers(r["primary"]["beneficiary"])
        self.assertEqual(tiers["TLT"], "sector_proxy")

    def test_unknown_family_falls_back_cleanly(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["XLE", "XOM"],
            mechanism_family="not_a_real_family",
        )
        # XOM is a single-name → direct_proxy regardless.
        # XLE's channel (equities) isn't primary for the empty pack.
        tiers_primary = _tiers(r["primary"]["beneficiary"])
        tiers_secondary = _tiers(r["secondary"]["beneficiary"])
        self.assertEqual(tiers_primary.get("XOM"), "direct_proxy")
        self.assertEqual(tiers_secondary.get("XLE"), "second_order")


# ---------------------------------------------------------------------------
# 5. Defensive behaviour
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):

    def test_empty_inputs_return_well_formed_shape(self):
        r = classify_and_rank_assets()
        self.assertFalse(r["available"])
        self.assertEqual(r["cleaned_beneficiary_tickers"], [])
        self.assertEqual(r["cleaned_loser_tickers"], [])
        for key in ("primary", "secondary", "hedge_signal", "excluded"):
            self.assertIn(key, r)

    def test_non_string_inputs_silently_dropped(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=[None, "XOM", 42, ""],
        )
        cleaned = r["cleaned_beneficiary_tickers"]
        self.assertEqual(cleaned, ["XOM"])

    def test_duplicates_deduped_preserving_order(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["XOM", "CVX", "XOM"],
        )
        cleaned = r["cleaned_beneficiary_tickers"]
        self.assertEqual(cleaned, ["XOM", "CVX"])

    def test_lowercase_tickers_normalised(self):
        r = classify_and_rank_assets(
            beneficiary_tickers=["xom", "xle"],
            mechanism_family="supply_shock",
        )
        cleaned = r["cleaned_beneficiary_tickers"]
        self.assertEqual(cleaned, ["XOM", "XLE"])


if __name__ == "__main__":
    unittest.main()

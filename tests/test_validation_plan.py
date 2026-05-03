"""
tests/test_validation_plan.py

Contract tests for the validation-plan composer.

Covers:
  1. Primary vs secondary vs signal asset tiering — direct single-name
     equities land in primary; thematic ETFs on non-primary channels
     drop to secondary; inverse / vol / FX ETFs move to signal.
  2. Confirming channels — LLM-provided + family-pack channels blend,
     each entry carries a signed expected_direction when the thesis
     classifier has a direction prior.
  3. Cascade channels — second-wave expectations stay separate from
     the first-wave confirming set.
  4. Disconfirming channels mirror confirming direction — up ↔ down,
     wider ↔ tighter.
  5. Expected order — stable, ordered token sequence that scorers can
     rely on without re-deriving.
  6. Empty-input defaults — an analysed event with no tickers and no
     channel hints still returns a shaped dict with available=False.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from validation_plan import compute_validation_plan


# ---------------------------------------------------------------------------
# 1. Asset tiering
# ---------------------------------------------------------------------------

class TestAssetTiering(unittest.TestCase):

    def test_direct_names_land_in_primary(self):
        plan = compute_validation_plan(
            headline="Oil supply shock — OPEC cuts output",
            mechanism_text="tighter oil supply benefits US producers",
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX", "XOM"],
            beneficiaries_text=["Chevron (CVX)", "Exxon (XOM)"],
        )
        syms = [a["symbol"] for a in plan["primary_assets"]]
        self.assertIn("CVX", syms)
        self.assertIn("XOM", syms)

    def test_sector_etf_lands_in_secondary_even_on_primary_channel(self):
        """Strict role separation: sector / commodity ETFs are
        indirect baskets, not direct expressions — they land in
        secondary regardless of family channel match.  Primary is
        reserved for direct single-name picks only."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["USO"],  # commodity ETF on commodities channel
        )
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertNotIn("USO", primary_syms)
        self.assertIn("USO", secondary_syms)

    def test_sector_etf_on_non_primary_channel_drops_to_secondary(self):
        # policy_surprise primary channels are rates/fx/vol — an energy
        # ETF is not primary for this family.
        plan = compute_validation_plan(
            mechanism_family="policy_surprise",
            beneficiary_tickers=["XLE"],
        )
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertNotIn("XLE", primary_syms)
        self.assertIn("XLE", secondary_syms)

    def test_inverse_and_fx_etfs_land_in_signal_tier(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            loser_tickers=["VXX", "UUP"],
        )
        signal_syms = [a["symbol"] for a in plan["signal_assets"]]
        self.assertIn("VXX", signal_syms)
        self.assertIn("UUP", signal_syms)


# ---------------------------------------------------------------------------
# 2. Confirming channels
# ---------------------------------------------------------------------------

class TestConfirmingChannels(unittest.TestCase):

    def test_confirming_blends_llm_and_family_pack(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",  # first: commodities, equities
            expected_first_order_channels=["fx"],  # extra LLM-provided
        )
        chs = [c["channel"] for c in plan["confirming_channels"]]
        # LLM-first ordering preserved, family pack appended.
        self.assertEqual(chs[0], "fx")
        self.assertIn("commodities", chs)
        self.assertIn("equities", chs)

    def test_inflationary_thesis_assigns_up_direction_to_commodities(self):
        plan = compute_validation_plan(
            headline="Oil supply squeeze raises inflation risk",
            mechanism_text="higher oil prices pass through to headline CPI",
            mechanism_family="commodity_squeeze",
        )
        commodities_entry = next(
            c for c in plan["confirming_channels"] if c["channel"] == "commodities"
        )
        self.assertEqual(commodities_entry["expected_direction"], "up")

    def test_disinflationary_thesis_assigns_down_direction_to_commodities(self):
        plan = compute_validation_plan(
            headline="Supply normalisation — inventory build",
            mechanism_text="inflation pressure fading as supply restored",
            mechanism_family="supply_normalization",
        )
        commodities_entry = next(
            c for c in plan["confirming_channels"] if c["channel"] == "commodities"
        )
        self.assertEqual(commodities_entry["expected_direction"], "down")

    def test_direction_unclear_when_thesis_is_none(self):
        plan = compute_validation_plan(
            headline="ambiguous event",
            mechanism_text="",
            mechanism_family="supply_shock",
        )
        # classify_thesis will return "none" on an uninformative headline;
        # direction must still be a token, falling back to "unclear".
        for c in plan["confirming_channels"]:
            self.assertIn(
                c["expected_direction"],
                {"up", "down", "wider", "tighter", "mixed", "unclear"},
            )


# ---------------------------------------------------------------------------
# 3. Cascade channels
# ---------------------------------------------------------------------------

class TestCascadeChannels(unittest.TestCase):

    def test_cascade_stays_separate_from_confirming(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            expected_first_order_channels=["commodities", "equities"],
            expected_second_order_channels=["credit", "rates"],
        )
        first = {c["channel"] for c in plan["confirming_channels"]}
        cascade = {c["channel"] for c in plan["cascade_channels"]}
        self.assertFalse(
            first & cascade,
            "confirming and cascade channels must be disjoint",
        )
        self.assertIn("credit", cascade)
        self.assertIn("rates", cascade)


# ---------------------------------------------------------------------------
# 4. Disconfirming channels mirror confirming
# ---------------------------------------------------------------------------

class TestDisconfirmingMirror(unittest.TestCase):

    def test_up_mirrors_to_down(self):
        plan = compute_validation_plan(
            headline="Oil supply squeeze raises inflation",
            mechanism_text="higher oil prices",
            mechanism_family="commodity_squeeze",
        )
        conf_by_ch = {c["channel"]: c for c in plan["confirming_channels"]}
        disc_by_ch = {c["channel"]: c for c in plan["disconfirming_channels"]}
        for ch, conf in conf_by_ch.items():
            if conf["expected_direction"] == "up":
                self.assertEqual(disc_by_ch[ch]["breaks_if"], "down")

    def test_every_confirming_channel_has_a_disconfirmation_entry(self):
        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            expected_first_order_channels=["credit", "equities"],
        )
        conf = {c["channel"] for c in plan["confirming_channels"]}
        disc = {c["channel"] for c in plan["disconfirming_channels"]}
        self.assertEqual(conf, disc)


# ---------------------------------------------------------------------------
# 5. Expected order
# ---------------------------------------------------------------------------

class TestExpectedOrder(unittest.TestCase):

    def test_expected_order_is_stable_and_primary_first(self):
        plan = compute_validation_plan(mechanism_family="supply_shock")
        order = plan["expected_order"]
        self.assertEqual(order[0], "primary_assets")
        self.assertEqual(order[1], "confirming_channels")
        self.assertIn("secondary_assets", order)
        self.assertIn("disconfirming_channels", order)
        self.assertIn("signal_assets", order)

    def test_expected_order_is_list_not_tuple(self):
        # UI consumers JSON-serialize; ensure the shape is a list.
        plan = compute_validation_plan(mechanism_family="none")
        self.assertIsInstance(plan["expected_order"], list)


# ---------------------------------------------------------------------------
# 6. Empty-input defaults
# ---------------------------------------------------------------------------

class TestEmptyInputDefaults(unittest.TestCase):

    def test_empty_inputs_still_return_shaped_dict(self):
        plan = compute_validation_plan()
        self.assertEqual(plan["primary_assets"], [])
        self.assertEqual(plan["secondary_assets"], [])
        self.assertEqual(plan["signal_assets"], [])
        # family=none → family pack is empty; no LLM channels → no confirming.
        self.assertEqual(plan["confirming_channels"], [])
        self.assertEqual(plan["disconfirming_channels"], [])
        self.assertFalse(plan["available"])
        # rationale must still be present so the UI can render a
        # placeholder line.
        self.assertIsInstance(plan["rationale"], str)
        self.assertTrue(plan["rationale"])

    def test_available_true_when_only_channels_present(self):
        """Even with no tickers, a channel expectation alone is enough
        for the validation engine to have something to score against."""
        plan = compute_validation_plan(mechanism_family="supply_shock")
        self.assertTrue(plan["available"])
        self.assertGreater(len(plan["confirming_channels"]), 0)


# ---------------------------------------------------------------------------
# 7. Per-asset enrichment — role / exposure / why / confirming channel
# ---------------------------------------------------------------------------

class TestPerAssetEnrichment(unittest.TestCase):
    """Each asset entry carries the structured per-asset rationale that
    the thesis generator promised: role, exposure, why, confirming
    channel, invalidating channel."""

    def test_every_asset_has_role_exposure_and_channel_fields(self):
        plan = compute_validation_plan(
            headline="Oil supply squeeze raises inflation",
            mechanism_text="higher oil prices feed through",
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["CVX"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        self.assertEqual(len(plan["primary_assets"]), 1)
        a = plan["primary_assets"][0]
        self.assertEqual(a["side"], "beneficiary")
        self.assertEqual(a["exposure"], "direct")
        self.assertIn("confirming_channel", a)
        self.assertIn("invalidating_channel", a)

    def test_hidden_mechanism_why_flows_into_asset_entries(self):
        plan = compute_validation_plan(
            headline="Venezuela licence allows Chevron to resume liftings",
            mechanism_text="heavy-sour crude feedstock restored",
            mechanism_family="supply_normalization",
            beneficiary_tickers=["CVX", "PBF"],
            beneficiaries_text=["Chevron (CVX)", "PBF"],
            hidden_mechanism={
                "bottleneck_type":   "commodity_quality_mismatch",
                "transmission_type": "physical_flow",
                "channel_domain":    "supply_chain",
                "asset_rationales":  {
                    "CVX": "Direct licence holder — upside tracks restored lift volumes.",
                    "PBF": "Gulf Coast coker refiner with heavy-sour configuration.",
                },
            },
        )
        why_by_symbol = {a["symbol"]: a.get("why") for a in plan["primary_assets"]}
        self.assertIn("Direct licence holder", why_by_symbol["CVX"])
        self.assertIn("Gulf Coast", why_by_symbol["PBF"])

    def test_asset_without_why_line_is_shaped_but_missing_why(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX"],
            hidden_mechanism={"asset_rationales": {"XOM": "not our ticker"}},
        )
        a = plan["primary_assets"][0]
        self.assertNotIn("why", a)

    def test_commodity_etf_gets_commodity_channel_as_confirming(self):
        plan = compute_validation_plan(
            headline="Oil supply squeeze raises inflation",
            mechanism_text="higher oil prices feed through",
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["USO"],  # commodity ETF → commodities channel
        )
        # Strict role separation: ETFs land in secondary (indirect),
        # not primary.  The confirming-channel enrichment still
        # applies regardless of bucket.
        a = plan["secondary_assets"][0]
        self.assertEqual(a["confirming_channel"]["channel"], "commodities")

    def test_invalidating_channel_mirrors_confirming(self):
        plan = compute_validation_plan(
            headline="Oil supply squeeze raises inflation",
            mechanism_text="higher oil prices feed through",
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["USO"],
        )
        a = plan["secondary_assets"][0]
        conf = a["confirming_channel"]
        inv  = a["invalidating_channel"]
        self.assertEqual(conf["channel"], inv["channel"])
        # up ↔ down mirror
        if conf["expected_direction"] == "up":
            self.assertEqual(inv["breaks_if"], "down")

    def test_signal_tier_asset_gets_signal_exposure_label(self):
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            loser_tickers=["VXX"],  # vol hedge → signal tier
        )
        self.assertEqual(len(plan["signal_assets"]), 1)
        a = plan["signal_assets"][0]
        self.assertEqual(a["exposure"], "signal")
        # Signal-tier assets still get a confirming channel assigned
        # (first plan entry) so downstream UI can render them.
        self.assertIn("confirming_channel", a)

    def test_secondary_asset_gets_secondary_exposure_label(self):
        # policy_surprise → energy ETF is second-order (non-primary channel)
        plan = compute_validation_plan(
            mechanism_family="policy_surprise",
            beneficiary_tickers=["XLE"],
        )
        self.assertEqual(len(plan["secondary_assets"]), 1)
        self.assertEqual(plan["secondary_assets"][0]["exposure"], "secondary")

    def test_no_confirming_channels_still_returns_asset_rows(self):
        """If the family is 'none' AND no LLM channels are provided,
        the plan has no confirming channels — but per-asset rows must
        still be emitted so the UI can render basic role/exposure."""
        plan = compute_validation_plan(
            mechanism_family="none",
            beneficiary_tickers=["CVX"],
        )
        self.assertEqual(len(plan["primary_assets"]), 1)
        a = plan["primary_assets"][0]
        self.assertEqual(a["side"], "beneficiary")
        self.assertEqual(a["exposure"], "direct")
        # No channels available → no confirming_channel / invalidating key
        self.assertNotIn("confirming_channel", a)
        self.assertNotIn("invalidating_channel", a)


class TestProxyEligibilityFilter(unittest.TestCase):
    """Stricter proxy-eligibility filter — every asset that survives
    classify_and_rank_assets must be classified as one of
    ``primary | secondary | hedge_signal | rejected``.  Off-pack
    proxies (broad/noisy ETFs that can't transmit through the family)
    are rejected; hedge assets stay signal-only regardless of pack;
    direct single-name picks always survive."""

    def test_direct_asset_kept_in_primary(self):
        """A direct single-name pick (CVX) on a family whose pack
        includes equities lands in primary with eligibility_status
        ``primary``."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        self.assertIn("CVX", primary_syms)
        cvx_row = next(a for a in plan["primary_assets"] if a["symbol"] == "CVX")
        self.assertEqual(cvx_row["eligibility_status"], "primary")

    def test_off_pack_etf_rejected(self):
        """A commodity ETF (CPER) on a family whose pack excludes
        commodities (fiscal_issuance: rates/fx + credit/equities) is
        rejected, not landed in secondary."""
        plan = compute_validation_plan(
            mechanism_family="fiscal_issuance",
            beneficiary_tickers=["CPER"],
        )
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        excluded_syms = [a["symbol"] for a in plan["excluded_assets"]]
        self.assertNotIn("CPER", primary_syms)
        self.assertNotIn("CPER", secondary_syms)
        self.assertIn("CPER", excluded_syms)
        cper_row = next(
            a for a in plan["excluded_assets"] if a["symbol"] == "CPER"
        )
        self.assertEqual(cper_row["eligibility_status"], "rejected")
        self.assertIn("commodities", cper_row["reason"])

    def test_hedge_asset_signal_only_even_when_off_pack(self):
        """A vol hedge (VXX) on a family whose pack excludes vol still
        lands as signal-only — it never gets rejected and never gets
        promoted to a primary thesis beneficiary."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",  # pack excludes vol
            beneficiary_tickers=["VXX"],
        )
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        signal_syms = [a["symbol"] for a in plan["signal_assets"]]
        self.assertNotIn("VXX", primary_syms)
        self.assertIn("VXX", signal_syms)
        vxx_row = next(a for a in plan["signal_assets"] if a["symbol"] == "VXX")
        self.assertEqual(vxx_row["eligibility_status"], "hedge_signal")
        self.assertEqual(vxx_row["exposure"], "signal")

    def test_weak_proxy_excluded(self):
        """A sector ETF on an off-pack channel (URA → commodities) for
        a regulation event (pack: equities, vol, credit) is excluded
        with a concrete rejection reason, not silently demoted."""
        plan = compute_validation_plan(
            mechanism_family="regulation",
            beneficiary_tickers=["URA"],
        )
        excluded_syms = [a["symbol"] for a in plan["excluded_assets"]]
        self.assertIn("URA", excluded_syms)
        ura_row = next(
            a for a in plan["excluded_assets"] if a["symbol"] == "URA"
        )
        self.assertEqual(ura_row["eligibility_status"], "rejected")

    def test_prefer_direct_demotes_sector_etf_on_same_channel(self):
        """When a direct single-name (CVX) is on the equities channel
        AND a sector ETF (XLE, also equities) is in the same input,
        the direct pick stays primary while the ETF demotes to
        secondary so the named-name read isn't diluted."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["CVX", "XLE"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertIn("CVX", primary_syms)
        self.assertIn("XLE", secondary_syms)
        self.assertNotIn("XLE", primary_syms)

    def test_every_asset_carries_eligibility_status(self):
        """Contract: every primary / secondary / signal asset row
        carries an explicit ``eligibility_status`` field, AND every
        excluded entry does too."""
        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            beneficiary_tickers=["KRE", "VXX", "URA"],
        )
        for bucket in ("primary_assets", "secondary_assets", "signal_assets"):
            for row in plan[bucket]:
                self.assertIn(
                    "eligibility_status", row,
                    f"{bucket} row missing eligibility_status: {row}",
                )
                self.assertIn(
                    row["eligibility_status"],
                    {"primary", "secondary", "hedge_signal"},
                    f"{bucket} got off-vocab status: {row['eligibility_status']!r}",
                )
        for row in plan["excluded_assets"]:
            self.assertEqual(row["eligibility_status"], "rejected")


class TestAssetRoleSeparation(unittest.TestCase):
    """Strict role separation in validation plans:
      * Primary = direct single-name expression of the thesis.
      * Secondary = indirect / second-order exposures (every ETF).
      * Hedge / signal = signal-only; never beneficiary or loser.
      * Off-channel asset role = rejected or demoted.
    """

    def test_direct_name_lands_in_primary(self):
        plan = compute_validation_plan(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["CVX"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        primary_syms   = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertIn("CVX", primary_syms)
        self.assertNotIn("CVX", secondary_syms)

    def test_sector_etf_alone_still_lands_in_secondary(self):
        """Even when no direct pick exists, an ETF stays in secondary —
        primary remains empty so the desk sees that no direct
        expression of the thesis was named."""
        plan = compute_validation_plan(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["USO"],
        )
        self.assertEqual(plan["primary_assets"], [])
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertIn("USO", secondary_syms)

    def test_direct_and_etf_cleanly_separated(self):
        """When both a direct name and an ETF are supplied on the same
        channel, the direct reads as primary and the ETF as
        secondary — no overlap, no demotion ambiguity."""
        plan = compute_validation_plan(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["CVX", "USO"],
            beneficiaries_text=["Chevron (CVX)"],
        )
        primary_syms   = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertEqual(primary_syms, ["CVX"])
        self.assertIn("USO", secondary_syms)
        self.assertNotIn("USO", primary_syms)
        self.assertNotIn("CVX", secondary_syms)

    def test_hedge_never_promoted_to_beneficiary_bucket(self):
        """A hedge / vol asset supplied on the beneficiary side stays
        in signal_assets and never appears in primary_assets or
        secondary_assets — even when both buckets are otherwise empty."""
        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            beneficiary_tickers=["VXX"],
        )
        primary_syms   = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        signal_syms    = [a["symbol"] for a in plan["signal_assets"]]
        self.assertNotIn("VXX", primary_syms)
        self.assertNotIn("VXX", secondary_syms)
        self.assertIn("VXX", signal_syms)

    def test_off_channel_asset_role_rejected(self):
        """A direct asset whose channel is outside the family's
        mechanism pack is rejected with wrong_channel — its role
        conflicts with what the family transmits through."""
        plan = compute_validation_plan(
            mechanism_family="fiscal_issuance",
            beneficiary_tickers=["CPER"],   # commodities; pack excludes
        )
        excluded_syms = [a["symbol"] for a in plan["excluded_assets"]]
        self.assertIn("CPER", excluded_syms)
        row = next(a for a in plan["excluded_assets"] if a["symbol"] == "CPER")
        self.assertEqual(row["rejection_reason"], "wrong_channel")


class TestProofItemAssetPrioritization(unittest.TestCase):
    """``proof_set_for_event`` and ``falsifier_set_for_event`` order
    items so channels covered by primary_assets surface first, then
    secondary, then hedge_or_signal_assets, then anything else."""

    def _event(self):
        return {
            "headline":           "Saudi liftings cut",
            "what_changed":       "Saudi Aramco cut crude liftings 1mbd.",
            "mechanism_summary":  (
                "Saudi liftings cut tightens Gulf coker feedstock and "
                "widens the WCS-WTI heavy-sour discount."
            ),
            "mechanism_family":   "commodity_squeeze",
            "beneficiaries":      ["Chevron"],
            "beneficiary_tickers": ["CVX"],
            "loser_tickers":       [],
            "assets_to_watch":     ["CVX"],
            "expected_first_order_channels":  ["commodities", "equities"],
            "expected_second_order_channels": [],
            "transmission_path":  [],
            "competing_thesis":   {"primary_thesis": "Saudi liftings cut"},
            "primary_assets":     [
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Gulf coker — heavy-sour feedstock benefits."},
            ],
            "secondary_assets":   [
                {"symbol": "USO", "rank": 1,
                 "rationale": "Oil ETF — broad complex exposure."},
            ],
            "hedge_or_signal_assets": [
                {"symbol": "VXX", "rank": 1,
                 "rationale": "Vol read on geopolitical risk."},
            ],
            "minimum_proof_set":  [
                {"observation": "WCS discount widens 2pp",
                 "channel": "commodities"},
            ],
            "key_falsifiers":     [
                {"observation": "Saudis walk back",
                 "channel": "commodities"},
            ],
            "critical_breakpoints": [],
        }

    def test_proof_items_ordered_primary_first(self):
        """CVX (equities channel) is primary; USO (commodities channel)
        is secondary.  proof_set_for_event must surface the equities
        item first — primary-asset channel beats secondary-asset
        channel even if family ordering would otherwise put commodities
        before equities."""
        from low_information_gate import proof_set_for_event
        out = proof_set_for_event(self._event())
        self.assertGreater(len(out), 1)
        primary_idx = next(
            (i for i, item in enumerate(out)
             if item["channel"] == "equities"),
            -1,
        )
        secondary_idx = next(
            (i for i, item in enumerate(out)
             if item["channel"] == "commodities"),
            -1,
        )
        self.assertGreaterEqual(primary_idx, 0)
        self.assertGreaterEqual(secondary_idx, 0)
        self.assertLess(
            primary_idx, secondary_idx,
            "primary-asset channel item must surface before "
            "secondary-asset channel item",
        )

    def test_falsifier_items_ordered_primary_first(self):
        from low_information_gate import falsifier_set_for_event
        out = falsifier_set_for_event(self._event())
        self.assertGreater(len(out), 0)
        # The first falsifier item's channel must be either primary or
        # secondary — never a signal-only channel when primary or
        # secondary items exist.
        first_channel = out[0]["channel"]
        self.assertIn(first_channel, ("equities", "commodities"))


class TestRejectionReasonVocabulary(unittest.TestCase):
    """Every rejected asset/proxy carries a short ``rejection_reason``
    drawn from the controlled vocabulary
    {too_broad, wrong_channel, duplicate_proxy, weak_exposure,
    signal_only_not_beneficiary}.  One test per value."""

    def _excluded_for(self, plan: dict, sym: str) -> dict:
        for row in plan["excluded_assets"]:
            if row.get("symbol") == sym:
                return row
        raise AssertionError(
            f"{sym} not found in excluded_assets: "
            f"{[r.get('symbol') for r in plan['excluded_assets']]}"
        )

    def test_too_broad_for_broad_market_index(self):
        """SPY is a broad-market index — too_broad."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["SPY"],
        )
        row = self._excluded_for(plan, "SPY")
        self.assertEqual(row["rejection_reason"], "too_broad")
        self.assertEqual(row["eligibility_status"], "rejected")

    def test_wrong_channel_for_off_pack_etf(self):
        """CPER is a commodities ETF; fiscal_issuance pack covers
        rates/fx/credit/equities — commodities is off-pack →
        wrong_channel."""
        plan = compute_validation_plan(
            mechanism_family="fiscal_issuance",
            beneficiary_tickers=["CPER"],
        )
        row = self._excluded_for(plan, "CPER")
        self.assertEqual(row["rejection_reason"], "wrong_channel")
        self.assertEqual(row["eligibility_status"], "rejected")

    def test_duplicate_proxy_for_second_sector_etf_same_channel(self):
        """SMH and SOXX are both equities-channel semis ETFs.  Keep
        the first as a secondary asset; reject the second as
        duplicate_proxy.  (Strict role separation: ETFs always land
        in secondary, not primary, so the kept basket lives there.)"""
        plan = compute_validation_plan(
            mechanism_family="industrial_policy",  # pack: equities primary
            beneficiary_tickers=["SMH", "SOXX"],
        )
        primary_syms   = [a["symbol"] for a in plan["primary_assets"]]
        secondary_syms = [a["symbol"] for a in plan["secondary_assets"]]
        self.assertNotIn("SMH",  primary_syms)
        self.assertNotIn("SOXX", primary_syms)
        self.assertIn("SMH", secondary_syms)
        self.assertNotIn("SOXX", secondary_syms)
        row = self._excluded_for(plan, "SOXX")
        self.assertEqual(row["rejection_reason"], "duplicate_proxy")

    def test_weak_exposure_for_foreign_listing(self):
        """Foreign-suffix listings can't be read on the US market
        feed → weak_exposure."""
        plan = compute_validation_plan(
            mechanism_family="supply_shock",
            beneficiary_tickers=["8035.T"],   # Tokyo-listed
        )
        row = self._excluded_for(plan, "8035.T")
        self.assertEqual(row["rejection_reason"], "weak_exposure")
        self.assertEqual(row["eligibility_status"], "rejected")

    def test_signal_only_not_beneficiary_records_misuse(self):
        """A hedge asset (VXX) supplied via beneficiary_tickers stays
        in signal_assets (not promoted) AND surfaces an excluded_assets
        entry tagged signal_only_not_beneficiary so the audit captures
        the misuse."""
        plan = compute_validation_plan(
            mechanism_family="bank_stress",  # pack includes vol
            beneficiary_tickers=["VXX"],
        )
        # Still kept in signal_assets — never promoted to primary.
        signal_syms = [a["symbol"] for a in plan["signal_assets"]]
        primary_syms = [a["symbol"] for a in plan["primary_assets"]]
        self.assertIn("VXX", signal_syms)
        self.assertNotIn("VXX", primary_syms)
        # Audit row captured.
        row = self._excluded_for(plan, "VXX")
        self.assertEqual(row["rejection_reason"], "signal_only_not_beneficiary")
        self.assertEqual(row["eligibility_status"], "rejected")
        self.assertEqual(row["side"], "beneficiary")

    def test_every_excluded_row_has_rejection_reason(self):
        """Contract: any row in ``excluded_assets`` must carry a
        rejection_reason from the controlled vocabulary."""
        from asset_selection import REJECTION_REASONS

        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            beneficiary_tickers=["KRE", "SPY", "8035.T", "VXX", "CPER"],
        )
        self.assertGreater(len(plan["excluded_assets"]), 0)
        for row in plan["excluded_assets"]:
            self.assertIn(
                "rejection_reason", row,
                f"excluded row missing rejection_reason: {row}",
            )
            self.assertIn(
                row["rejection_reason"], REJECTION_REASONS,
                f"off-vocab rejection_reason: {row['rejection_reason']!r}",
            )


class TestSignalAssetsCarryRealChannel(unittest.TestCase):
    """Hedge / inverse / vol / FX assets must map to a named macro
    channel (vol / fx / equities / rates) — not the ``"signal"``
    pseudo-channel.  Otherwise a confirming signal asset never aligns
    with channel-scoped proof evaluation."""

    def test_vix_signal_asset_maps_to_vol(self):
        plan = compute_validation_plan(
            mechanism_family="bank_stress",
            beneficiary_tickers=["VXX"],
            expected_first_order_channels=["vol"],
        )
        self.assertEqual(len(plan["signal_assets"]), 1)
        sa = plan["signal_assets"][0]
        # Confirming channel must be a real macro channel — vol — not "signal".
        self.assertIn("confirming_channel", sa)
        self.assertEqual(sa["confirming_channel"]["channel"], "vol")

    def test_fx_signal_asset_maps_to_fx(self):
        plan = compute_validation_plan(
            mechanism_family="policy_surprise",
            beneficiary_tickers=["UUP"],
            expected_first_order_channels=["fx"],
        )
        self.assertEqual(len(plan["signal_assets"]), 1)
        sa = plan["signal_assets"][0]
        self.assertEqual(sa["confirming_channel"]["channel"], "fx")

    def test_inverse_bond_signal_asset_maps_to_rates(self):
        plan = compute_validation_plan(
            mechanism_family="fiscal_issuance",
            beneficiary_tickers=["TBT"],
            expected_first_order_channels=["rates"],
        )
        self.assertEqual(len(plan["signal_assets"]), 1)
        sa = plan["signal_assets"][0]
        self.assertEqual(sa["confirming_channel"]["channel"], "rates")


if __name__ == "__main__":
    unittest.main()

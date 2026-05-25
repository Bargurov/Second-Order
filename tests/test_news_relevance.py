"""Tests for ``news_relevance.is_relevant`` — keyword allowlist coverage.

Regression suite pinning that economically significant headlines from
underrepresented market-moving domains (healthcare, agriculture,
climate/energy-transition, credit/banking, consumer/housing/employment)
are admitted by the relevance filter, while generic soft-news variants
of those same topic words are correctly rejected.

Read-only contract:

* No DB, ``yfinance``, ``market_data``, paid provider, LLM, or
  FastAPI surface is imported.
* No mutation of any file — pure-function tests only.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from news_relevance import is_relevant  # noqa: E402


# ---------------------------------------------------------------------------
# Audit false-negative regression — these seven headlines were identified
# as market-significant but silently dropped by the pre-expansion filter.
# ---------------------------------------------------------------------------


class TestAuditFalseNegativeRegression(unittest.TestCase):
    """Every headline from the read-only audit that was a false negative
    must now pass ``is_relevant``."""

    def test_fda_drug_approval(self) -> None:
        self.assertTrue(is_relevant(
            "FDA approves first gene therapy for sickle cell disease"))

    def test_housing_mortgage(self) -> None:
        self.assertTrue(is_relevant(
            "US housing starts fall 14% as mortgage rates hit 7.5%"))

    def test_credit_rating_downgrade(self) -> None:
        self.assertTrue(is_relevant(
            "Moody's downgrades US sovereign credit rating to Aa1"))

    def test_agriculture_corn_drought(self) -> None:
        self.assertTrue(is_relevant(
            "Brazil corn harvest forecast cut 8% on drought"))

    def test_carbon_border(self) -> None:
        self.assertTrue(is_relevant(
            "EU carbon border adjustment mechanism takes effect"))

    def test_vehicle_recall(self) -> None:
        self.assertTrue(is_relevant(
            "Tesla recalls 2 million vehicles over Autopilot defect"))

    def test_tech_layoffs(self) -> None:
        self.assertTrue(is_relevant(
            "Amazon announces 18,000 layoffs in largest tech reduction"))


# ---------------------------------------------------------------------------
# Soft-news rejection — generic lifestyle headlines using the same topic
# words must remain rejected.
# ---------------------------------------------------------------------------


class TestSoftNewsRejection(unittest.TestCase):
    """Headlines that share topic words with the new keywords but lack
    an economic/policy transmission path must still be rejected."""

    def test_rejects_celebrity_coffee(self) -> None:
        self.assertFalse(is_relevant(
            "Celebrity launches coffee brand"))

    def test_rejects_climate_awareness_fair(self) -> None:
        self.assertFalse(is_relevant(
            "Local charity hosts climate awareness fair"))

    def test_rejects_hospital_charity_gala(self) -> None:
        self.assertFalse(is_relevant(
            "Hospital charity gala raises funds"))

    def test_rejects_classic_auto_show(self) -> None:
        self.assertFalse(is_relevant(
            "Car enthusiast meetup announces classic auto show"))

    def test_rejects_lifestyle_photo_event(self) -> None:
        self.assertFalse(is_relevant(
            "Eclipse draws thousands of amateur photographers"))

    def test_rejects_fall_festival(self) -> None:
        self.assertFalse(is_relevant(
            "Pumpkin maze opens for fall festival season"))

    def test_rejects_pumpkin_harvest(self) -> None:
        self.assertFalse(is_relevant(
            "Family picks pumpkins at county fair"))

    def test_rejects_drought_metaphor(self) -> None:
        self.assertFalse(is_relevant(
            "Director laments creative ideas in short supply"))


# ---------------------------------------------------------------------------
# Per-domain positive coverage — economically significant headlines
# from each newly covered domain must pass.
# ---------------------------------------------------------------------------


class TestHealthcareRegulatory(unittest.TestCase):

    def test_fda_approval(self) -> None:
        self.assertTrue(is_relevant(
            "FDA approves Novo Nordisk obesity drug for broader use"))

    def test_ema_approval(self) -> None:
        self.assertTrue(is_relevant(
            "EMA grants conditional approval for mRNA cancer vaccine"))

    def test_clinical_trial(self) -> None:
        self.assertTrue(is_relevant(
            "Phase 3 clinical trial shows 40% reduction in heart attacks"))

    def test_drug_price(self) -> None:
        self.assertTrue(is_relevant(
            "Medicare drug price negotiations cut costs for top 10 drugs"))

    def test_generic_drug(self) -> None:
        self.assertTrue(is_relevant(
            "India generic drug exports to Africa surge after patent expiry"))

    def test_biosimilar(self) -> None:
        self.assertTrue(is_relevant(
            "Biosimilar competition drives down Humira pricing"))

    def test_medicare(self) -> None:
        self.assertTrue(is_relevant(
            "Medicare spending projected to exceed $1 trillion by 2028"))

    def test_medicaid(self) -> None:
        self.assertTrue(is_relevant(
            "States face Medicaid funding shortfall after federal match expires"))

    def test_patent_expiry(self) -> None:
        self.assertTrue(is_relevant(
            "Pfizer faces patent expiry on $20 billion drug portfolio"))


class TestAgricultureFood(unittest.TestCase):

    def test_soybean(self) -> None:
        self.assertTrue(is_relevant(
            "USDA raises soybean export forecast amid strong China demand"))

    def test_corn_crop(self) -> None:
        self.assertTrue(is_relevant(
            "US corn crop estimate revised lower on midwest heat"))

    def test_livestock(self) -> None:
        self.assertTrue(is_relevant(
            "Cattle livestock prices hit 10-year high on feed cost surge"))

    def test_fertilizer(self) -> None:
        self.assertTrue(is_relevant(
            "Global fertilizer prices drop as Russian exports resume"))

    def test_fertiliser_uk(self) -> None:
        self.assertTrue(is_relevant(
            "UK fertiliser costs ease after gas price retreat"))

    def test_drought(self) -> None:
        self.assertTrue(is_relevant(
            "Argentina drought wipes out 30% of wheat harvest"))

    def test_el_nino(self) -> None:
        self.assertTrue(is_relevant(
            "El Nino conditions threaten Southeast Asian rice output"))

    def test_el_nino_unicode(self) -> None:
        self.assertTrue(is_relevant(
            "El Niño drives commodity price volatility across Asia"))

    def test_la_nina(self) -> None:
        self.assertTrue(is_relevant(
            "La Nina forecast boosts Australian wheat production outlook"))

    def test_usda(self) -> None:
        self.assertTrue(is_relevant(
            "USDA crop report shows record corn planting acreage"))

    def test_harvest(self) -> None:
        self.assertTrue(is_relevant(
            "Ukraine grain harvest falls 25% amid ongoing conflict"))

    def test_crops_plural(self) -> None:
        self.assertTrue(is_relevant(
            "US crops damaged by early frost across Great Plains"))


class TestClimateEnergyTransition(unittest.TestCase):

    def test_carbon_tax(self) -> None:
        self.assertTrue(is_relevant(
            "Canada raises carbon tax to $80 per tonne"))

    def test_carbon_border(self) -> None:
        self.assertTrue(is_relevant(
            "EU carbon border adjustment hits steel and cement imports"))

    def test_carbon_credit(self) -> None:
        self.assertTrue(is_relevant(
            "Voluntary carbon credit market reaches $2 billion"))

    def test_wind_farm(self) -> None:
        self.assertTrue(is_relevant(
            "Offshore wind farm approvals stall on cost overruns"))

    def test_ev_mandate(self) -> None:
        self.assertTrue(is_relevant(
            "California EV mandate forces automakers to accelerate plans"))

    def test_renewable_energy(self) -> None:
        self.assertTrue(is_relevant(
            "Renewable energy investment surpasses fossil fuels globally"))

    def test_emissions_trading(self) -> None:
        self.assertTrue(is_relevant(
            "EU emissions trading scheme prices hit record high"))

    def test_hydrogen(self) -> None:
        self.assertTrue(is_relevant(
            "Green hydrogen projects attract $50 billion in commitments"))

    def test_solar_energy(self) -> None:
        self.assertTrue(is_relevant(
            "Solar panel installations double as module prices fall"))

    def test_battery_supply(self) -> None:
        self.assertTrue(is_relevant(
            "Battery supply chain bottleneck slows EV production"))


class TestCreditBankingInsurance(unittest.TestCase):

    def test_credit_rating(self) -> None:
        self.assertTrue(is_relevant(
            "Fitch places France on credit rating watch negative"))

    def test_downgrade(self) -> None:
        self.assertTrue(is_relevant(
            "S&P downgrades three regional banks on deposit outflow"))

    def test_bank_failure(self) -> None:
        self.assertTrue(is_relevant(
            "FDIC seizes mid-size bank after deposit outflow accelerates"))

    def test_fdic(self) -> None:
        self.assertTrue(is_relevant(
            "FDIC proposes higher deposit insurance premiums"))

    def test_reinsurance(self) -> None:
        self.assertTrue(is_relevant(
            "Reinsurance rates jump 20% after record hurricane season"))

    def test_insurance_loss(self) -> None:
        self.assertTrue(is_relevant(
            "Insured insurance loss from wildfire exceeds $30 billion"))

    def test_deposit_outflow(self) -> None:
        self.assertTrue(is_relevant(
            "Regional banks report deposit outflow slowing in Q2"))


class TestConsumerHousingEmployment(unittest.TestCase):

    def test_housing_starts(self) -> None:
        self.assertTrue(is_relevant(
            "Housing starts plunge to lowest level since 2020"))

    def test_mortgage_rate(self) -> None:
        self.assertTrue(is_relevant(
            "30-year mortgage rate climbs above 7% for first time"))

    def test_home_price(self) -> None:
        self.assertTrue(is_relevant(
            "US home price index posts largest monthly decline in a decade"))

    def test_retail_sales(self) -> None:
        self.assertTrue(is_relevant(
            "December retail sales miss expectations by wide margin"))

    def test_consumer_spending(self) -> None:
        self.assertTrue(is_relevant(
            "Consumer spending growth stalls as credit card debt rises"))

    def test_consumer_confidence(self) -> None:
        self.assertTrue(is_relevant(
            "Consumer confidence drops to two-year low on inflation"))

    def test_job_cuts(self) -> None:
        self.assertTrue(is_relevant(
            "Wall Street job cuts deepen as deal flow dries up"))

    def test_layoff(self) -> None:
        self.assertTrue(is_relevant(
            "Meta announces fresh layoff round affecting 10,000 staff"))

    def test_unemployment_claim(self) -> None:
        self.assertTrue(is_relevant(
            "Weekly unemployment claims surge to 280,000"))

    def test_auto_recall(self) -> None:
        self.assertTrue(is_relevant(
            "GM issues auto recall covering 800,000 trucks"))

    def test_product_recall(self) -> None:
        self.assertTrue(is_relevant(
            "Boeing recalls 737 MAX aircraft over door plug defect"))


# ---------------------------------------------------------------------------
# Existing domain coverage — verify pre-existing keywords still work.
# ---------------------------------------------------------------------------


class TestExistingCoverageUnchanged(unittest.TestCase):

    def test_tariff(self) -> None:
        self.assertTrue(is_relevant(
            "EU imposes retaliatory tariffs on US steel"))

    def test_opec(self) -> None:
        self.assertTrue(is_relevant(
            "OPEC agrees to production cut as oil prices fall"))

    def test_federal_reserve(self) -> None:
        self.assertTrue(is_relevant(
            "Federal Reserve signals rate cut amid recession fears"))

    def test_semiconductor(self) -> None:
        self.assertTrue(is_relevant(
            "TSMC expands chip production amid semiconductor shortage"))

    def test_sanctions(self) -> None:
        self.assertTrue(is_relevant(
            "US sanctions Russian oligarchs over Ukraine invasion"))

    def test_rejects_sports(self) -> None:
        self.assertFalse(is_relevant(
            "Manchester United signs new striker for record fee"))

    def test_rejects_entertainment(self) -> None:
        self.assertFalse(is_relevant(
            "Taylor Swift announces new world tour dates"))

    def test_rejects_lifestyle(self) -> None:
        self.assertFalse(is_relevant(
            "Best recipes for a summer barbecue"))

    def test_rejects_celebrity(self) -> None:
        self.assertFalse(is_relevant(
            "Royal family attends charity gala in London"))

    def test_rejects_local_crime(self) -> None:
        self.assertFalse(is_relevant(
            "Police investigate robbery at downtown convenience store"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

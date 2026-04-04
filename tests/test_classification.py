import sys
import unittest

sys.path.insert(0, ".")
from classify import classify_persistence, classify_stage


class ClassificationSmokeTests(unittest.TestCase):
    def test_example_headlines(self) -> None:
        cases = [
            {
                "headline": "US may impose new export control restrictions on chip sales to China",
                "stage": "anticipation",
                "persistence": "structural",
            },
            {
                "headline": "Israel and Hamas agree to a ceasefire deal after weeks of fighting",
                "stage": "de-escalation",
                "persistence": "medium",
            },
            {
                "headline": "Oil terminals reopen as shipping routes are restored",
                "stage": "normalization",
                "persistence": "medium",
            },
            {
                "headline": "Country X launches missile attack on border facilities",
                "stage": "escalation",
                "persistence": "medium",
            },
            {
                "headline": "Government announces new industrial support package",
                "stage": "realized",
                "persistence": "medium",
            },
        ]

        for case in cases:
            with self.subTest(headline=case["headline"]):
                self.assertEqual(classify_stage(case["headline"]), case["stage"])
                self.assertEqual(
                    classify_persistence(case["headline"]),
                    case["persistence"],
                )

    def test_edge_case_headlines(self) -> None:
        cases = [
            {
                "headline": "US considers easing sanctions on Venezuelan oil exports",
                "stage": "anticipation",
                "persistence": "structural",
            },
            {
                "headline": "Iran launches missile strike",
                "stage": "escalation",
                "persistence": "medium",
            },
            {
                "headline": "Ceasefire talks begin",
                "stage": "anticipation",
                "persistence": "medium",
            },
            {
                "headline": "OPEC expected to discuss output changes",
                "stage": "anticipation",
                "persistence": "medium",
            },
            {
                "headline": "Tariff proposal may raise import costs",
                "stage": "anticipation",
                "persistence": "structural",
            },
            {
                "headline": "Export ban takes effect",
                "stage": "realized",
                "persistence": "structural",
            },
        ]

        for case in cases:
            with self.subTest(headline=case["headline"]):
                self.assertEqual(classify_stage(case["headline"]), case["stage"])
                self.assertEqual(
                    classify_persistence(case["headline"]),
                    case["persistence"],
                )


class ClassifyPersistenceRegressionTests(unittest.TestCase):
    """Regression tests for the vocabulary gap in classify_persistence().

    The original six structural keywords missed: subsidies, premiums,
    investment restrictions, and industrial-policy language.
    """

    def test_subsidy_package_is_structural(self) -> None:
        headline = "EU announces multi-year industrial subsidy package for semiconductor fabs"
        self.assertEqual(classify_persistence(headline), "structural")

    def test_insurance_premium_surge_is_structural(self) -> None:
        # 'premium' (stem) matches 'premiums' via substring
        headline = "War-risk insurance premiums surge for Black Sea shipping routes"
        self.assertEqual(classify_persistence(headline), "structural")

    def test_temporary_production_cut_is_medium(self) -> None:
        # No structural or transient keyword → falls through to default 'medium'
        headline = "OPEC announces temporary 500k barrel production cut for Q3"
        self.assertEqual(classify_persistence(headline), "medium")

    def test_outbound_investment_restriction_is_structural(self) -> None:
        # 'restrict' stem matches 'restricts'
        headline = "US restricts outbound investment in Chinese AI companies"
        self.assertEqual(classify_persistence(headline), "structural")


class ClassifyStageRegressionTests(unittest.TestCase):
    """Regression tests for the two confirmed substring-matching bugs.

    Bug 1: 'expected' was matching inside 'unexpectedly' — word-boundary fix.
    Bug 2: 'talks' (anticipation) was beating 'resume' (normalization) — compound fix.
    """

    def test_unexpectedly_is_not_anticipation(self) -> None:
        # 'expected' must NOT fire inside 'unexpectedly'
        headline = "Central bank unexpectedly raises policy rate after currency selloff"
        self.assertEqual(classify_stage(headline), "realized")

    def test_resume_talks_is_normalization_not_anticipation(self) -> None:
        # 'resume' + 'talks' together → normalization wins over anticipation
        headline = "US and China resume trade talks after months of tariff disputes"
        self.assertEqual(classify_stage(headline), "normalization")

    def test_plain_expected_still_anticipation(self) -> None:
        # 'expected' on its own must still return anticipation
        headline = "Federal Reserve expected to signal slower rate cuts amid sticky inflation"
        self.assertEqual(classify_stage(headline), "anticipation")

    def test_ceasefire_agreement_still_deescalation(self) -> None:
        # de-escalation path must be unaffected by the patch
        headline = "Israel and Hamas reach ceasefire agreement after weeks of fighting"
        self.assertEqual(classify_stage(headline), "de-escalation")

    def test_missile_strikes_still_escalation(self) -> None:
        # escalation path must be unaffected by the patch
        headline = "Missile strikes hit energy infrastructure near a major Black Sea port"
        self.assertEqual(classify_stage(headline), "escalation")

    def test_retaliatory_duties_is_escalation(self) -> None:
        # Regression: 'retaliatory' must match now that explicit word forms replace the stem
        headline = "European Union approves retaliatory duties on selected US industrial goods"
        self.assertEqual(classify_stage(headline), "escalation")

    def test_terminal_restarts_is_normalization(self) -> None:
        # Regression: 'restarts' must match now that explicit word forms replace the stem
        headline = "Major LNG export terminal restarts operations after unplanned outage"
        self.assertEqual(classify_stage(headline), "normalization")


if __name__ == "__main__":
    unittest.main()

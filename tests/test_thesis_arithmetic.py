"""Decimal arithmetic and the status rules of the committed thesis (thesis-arithmetic). Nothing here reaches a network."""
from decimal import Decimal
import unittest

from second_order import thesis_arithmetic

D = Decimal


class ShownValueTests(unittest.TestCase):
    def test_shown_values_parse_every_grouping_the_sources_use(self):
        cases = [("23,000", "23000"), ("23 000", "23000"), ("23 000", "23000"), ("23 000", "23000"),
                 ("23 000", "23000"), ("1,234.5", "1234.5"), ("-400", "-400"), ("12%", "12"),
                 ("$9,500", "9500"), ("53.2", "53.2"), ("1 234 567", "1234567"), ("-1,234", "-1234"),
                 ("$12.5%", "12.5")]
        for text, value in cases:
            with self.subTest(text=text):
                self.assertEqual(thesis_arithmetic.shown_value(text), Decimal(value))

    def test_shown_values_that_need_a_conversion_or_are_malformed_are_refused(self):
        bad = ["23 million", "1.2e3", "23,00", "23,000 000", "", "NaN", "--4", "-$400", "$$4", "4%%", "$", "%",
               "23,000 000", "1,234,5", "1234,567", " 23", "23 ", "Infinity", "4.", ".5", "12 %"]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                thesis_arithmetic.shown_value(text)

    def test_decimal_of_accepts_only_plain_decimals(self):
        self.assertEqual(thesis_arithmetic.decimal_of("-12.50"), D("-12.50"))
        self.assertEqual(thesis_arithmetic.decimal_of("7"), D(7))
        for text in ["1,000", "1e3", "+5", "", " 5", "5%", "NaN"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                thesis_arithmetic.decimal_of(text)


class StatusRuleTests(unittest.TestCase):
    def test_a_trending_series_reads_strengthening_only_past_the_material_change(self):
        rs = thesis_arithmetic.reason_state
        self.assertEqual(rs(D(100), D(105), "higher", D(5)), "strengthening")  # equal to m counts as a change
        self.assertEqual(rs(D(100), D("104.9"), "higher", D(5)), "unchanged")
        self.assertEqual(rs(D(100), D(90), "higher", D(5)), "weakening")
        self.assertEqual(rs(D(100), D(90), "lower", D(5)), "strengthening")
        self.assertEqual(rs(D(100), D(110), "lower", D(5)), "weakening")
        self.assertEqual(rs(D(100), D(95), "higher", D(5)), "weakening")

    def test_risk_state(self):
        rk = thesis_arithmetic.risk_state
        self.assertEqual(rk(D(100), D(110), "higher", D(5)), "materialising")
        self.assertEqual(rk(D(100), D(90), "higher", D(5)), "receding")
        self.assertEqual(rk(D(100), D(90), "lower", D(5)), "materialising")
        self.assertEqual(rk(D(100), D("102"), "higher", D(5)), "unchanged")
        self.assertEqual(rk(D(100), D(105), "higher", D(5)), "materialising")

    def test_direction_vocabulary_is_closed(self):
        with self.assertRaises(ValueError):
            thesis_arithmetic.reason_state(D(1), D(2), "up", D(1))
        with self.assertRaises(ValueError):
            thesis_arithmetic.reason_state(D(1), D(2), "same", D(1))
        with self.assertRaises(ValueError):
            thesis_arithmetic.risk_state(D(1), D(2), "up", D(1))
        with self.assertRaises(ValueError):
            thesis_arithmetic.condition_state(D(1), "equal", D(1))

    def test_moved(self):
        self.assertEqual(thesis_arithmetic.moved(D(1), D(2)), "higher")
        self.assertEqual(thesis_arithmetic.moved(D(2), D(1)), "lower")
        self.assertEqual(thesis_arithmetic.moved(D("1.0"), D(1)), "same")

    def test_negative_previous_values_use_their_magnitude(self):
        self.assertEqual(thesis_arithmetic.change_pct(D(-400), D(-200)), D(50))
        self.assertEqual(thesis_arithmetic.change_pct(D(-400), D(-600)), D(-50))
        self.assertEqual(thesis_arithmetic.reason_state(D(-400), D(-200), "higher", D(5)), "strengthening")

    def test_change_pct_is_exact(self):
        self.assertEqual(thesis_arithmetic.change_pct(D(100), D("104.9")), D("4.9"))

    def test_a_zero_previous_value_has_no_change(self):
        with self.assertRaises(ZeroDivisionError):
            thesis_arithmetic.change_pct(D(0), D(5))

    def test_conditions_at_the_threshold_have_not_happened(self):
        cs = thesis_arithmetic.condition_state
        self.assertEqual(cs(D(10), "below", D(10)), "not_happened")
        self.assertEqual(cs(D(10), "above", D(10)), "not_happened")
        self.assertEqual(cs(D(9), "below", D(10)), "happened")
        self.assertEqual(cs(D("10.01"), "above", D(10)), "happened")
        self.assertEqual(cs(D(11), "below", D(10)), "not_happened")
        self.assertEqual(cs(D(9), "above", D(10)), "not_happened")


class BalanceAndCostTests(unittest.TestCase):
    def test_the_balance_labels_its_sign_and_counts_weeks(self):
        self.assertEqual(thesis_arithmetic.balance(D(26000), D(26500)),
                         {"gap": D(-500), "label": "deficit", "weeks": D("1.0")})
        self.assertEqual(thesis_arithmetic.balance(D(27000), D(26500)),
                         {"gap": D(500), "label": "surplus", "weeks": D("1.0")})
        self.assertEqual(thesis_arithmetic.balance(D(100), D(100)),
                         {"gap": D(0), "label": "balanced", "weeks": D("0.0")})

    def test_balance_refuses_a_non_positive_demand(self):
        for d in (D(0), D(-5)):
            with self.subTest(demand=d), self.assertRaises(ValueError):
                thesis_arithmetic.balance(D(10), d)

    def test_weeks_round_half_even_to_a_tenth(self):
        # 52 * 1 / 1040 = 0.05 -> 0.0 ; 52 * 3 / 1040 = 0.15 -> 0.2
        self.assertEqual(thesis_arithmetic.balance(D(1041), D(1040))["weeks"], D("0.0"))
        self.assertEqual(thesis_arithmetic.balance(D(1043), D(1040))["weeks"], D("0.2"))
        # Ruling R10: multiply before dividing. 21 * 52 / 208 is exactly 5.25 -> 5.2 (half to even), but 21 / 208 does
        # not terminate, so dividing first lands just past the half and gives 5.3. 107 * 52 / 1040 = 5.35 -> 5.4.
        for supply, demand, weeks in ((187, 208, "5.2"), (229, 208, "5.2"), (933, 1040, "5.4"), (1147, 1040, "5.4")):
            with self.subTest(supply=supply, demand=demand):
                self.assertEqual(thesis_arithmetic.balance(D(supply), D(demand))["weeks"], D(weeks))

    def test_per_unit_cost_and_share(self):
        self.assertEqual(thesis_arithmetic.per_unit_cost(D("53.2"), D(9500)), D(505))
        self.assertEqual(thesis_arithmetic.share_pct(D(505), D(45000)), D("1.1"))

    def test_rounding_is_half_even(self):
        self.assertEqual(thesis_arithmetic.per_unit_cost(D("1"), D("2500")), D(2))   # 2.5 -> 2
        self.assertEqual(thesis_arithmetic.per_unit_cost(D("1"), D("3500")), D(4))   # 3.5 -> 4
        self.assertEqual(thesis_arithmetic.share_pct(D("1.25"), D(100)), D("1.2"))
        self.assertEqual(thesis_arithmetic.share_pct(D("1.35"), D(100)), D("1.4"))

    def test_share_refuses_a_non_positive_whole(self):
        for w in (D(0), D(-1)):
            with self.subTest(whole=w), self.assertRaises(ValueError):
                thesis_arithmetic.share_pct(D(1), w)


class DisplayTests(unittest.TestCase):
    def test_display_rounds_half_even_and_groups(self):
        self.assertEqual(thesis_arithmetic.display(D("-1234.25"), 1), "-1,234.2")
        self.assertEqual(thesis_arithmetic.display(D("1234.35"), 1), "1,234.4")
        self.assertEqual(thesis_arithmetic.display(D(1234567), 0), "1,234,567")

    def test_display_sign_and_places(self):
        self.assertEqual(thesis_arithmetic.display(D(-500), 0), "-500")
        self.assertEqual(thesis_arithmetic.display(D("1.0"), 1), "1.0")
        self.assertEqual(thesis_arithmetic.display(D(1), 2), "1.00")
        self.assertEqual(thesis_arithmetic.display(D("0.04"), 1), "0.0")

    def test_a_value_that_rounds_to_zero_carries_no_minus_sign(self):
        self.assertEqual(thesis_arithmetic.display(D("-0.04"), 1), "0.0")


if __name__ == "__main__":
    unittest.main()

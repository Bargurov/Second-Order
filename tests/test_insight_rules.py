"""Measurements and rules of the Treasury findings pilot on hand-built SYNTHETIC grids (insight_rules). No I/O."""
from datetime import date
from decimal import Decimal
import unittest

from insight_fakes import pattern
from second_order import insight_rules as rules
from second_order.market_calendar import expected_sessions

START, END = date(2024, 1, 2), date(2026, 9, 30)
SESSIONS = sorted(expected_sessions(START, END))
EVENT = date(2026, 9, 16)  # A Wednesday session: B6 9/8, B1 9/15, A1 9/17, A5 9/23.


def grid(overrides: dict | None = None, value=pattern) -> rules.Grid:
    """Every yield series on every SIFMA session; overrides map (series, date) to text or None (missing)."""
    overrides = overrides or {}
    return rules.Grid({series_id: [(day, overrides.get((series_id, day), value(series_id, day)))
                                   for day in SESSIONS] for series_id in rules.YIELDS})


def at(day: date, series_id: str, delta: str, base: rules.Grid | None = None) -> str:
    """The pattern's value on a date shifted by delta percentage points."""
    return f"{Decimal(pattern(series_id, day)) + Decimal(delta):.2f}"


N2, N10, R10, N3M = "RIFLGFCY02_N.B", "RIFLGFCY10_N.B", "RIFLGFCY10_XII_N.B", "RIFLGFCM03_N.B"
B6, B1, A1, A5 = date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 17), date(2026, 9, 23)


def check(result: dict, rule: str, subject, window) -> dict:
    return next(item for item in result["checks"] if (item["rule"], item["subject"], item["window"]) ==
                (rule, subject, window))


class WindowTests(unittest.TestCase):
    def test_windows_on_a_session_a_weekend_and_a_holiday(self):
        result = rules.evaluate(grid(), EVENT)
        self.assertEqual({key: (value["start"], value["end"], value["span"]) for key, value in result["windows"].items()},
                         {"W1": ("2026-09-15", "2026-09-17", 2), "W5": ("2026-09-15", "2026-09-23", 6),
                          "PRE": ("2026-09-08", "2026-09-15", 5)})
        self.assertTrue(result["event_on_grid"])
        weekend = rules.evaluate(grid(), date(2026, 9, 19))
        self.assertEqual((weekend["windows"]["W1"]["start"], weekend["windows"]["W1"]["end"],
                          weekend["windows"]["W1"]["span"]), ("2026-09-18", "2026-09-21", 1))
        labor_day = rules.evaluate(grid(), date(2026, 9, 7))  # A SIFMA holiday: not a grid date.
        self.assertEqual((labor_day["windows"]["W1"]["start"], labor_day["windows"]["W1"]["end"],
                          labor_day["windows"]["W1"]["span"], labor_day["event_on_grid"]),
                         ("2026-09-04", "2026-09-08", 1, False))

    def test_a_window_past_the_data_or_without_history_is_unavailable(self):
        late = rules.evaluate(grid(), date(2026, 9, 28))
        self.assertEqual((late["state"], late["problem"]), ("unavailable", "window_not_in_data"))
        early = rules.evaluate(grid(), date(2024, 1, 5))
        self.assertEqual((early["state"], early["problem"]), ("unavailable", "not_enough_history"))
        self.assertIsNone(rules.inputs(grid(), date(2026, 9, 28)))


class ChangeTests(unittest.TestCase):
    def test_changes_are_exact_basis_points_from_the_source_text(self):
        built = grid({(N10, B1): "4.12", (N10, A1): "4.31", (R10, B1): "1.80", (R10, A1): "1.75"})
        table = rules.evaluate(built, EVENT)["table"]
        self.assertEqual(table["n10:W1"]["change_bp"], "19")
        self.assertEqual(table["r10:W1"]["change_bp"], "-5")
        self.assertEqual(table["be10:W1"]["change_bp"], "24")  # (4.31 - 1.75) - (4.12 - 1.80), exactly.
        self.assertEqual([value["text"] for value in table["be10:W1"]["end"]["values"]], ["4.31", "1.75"])

    def test_a_missing_endpoint_stays_unavailable_and_is_never_moved(self):
        result = rules.evaluate(grid({(N10, A1): None}), EVENT)
        entry = result["table"]["n10:W1"]
        self.assertIsNone(entry["change_bp"])
        self.assertEqual(entry["end"]["date"], "2026-09-17")  # The endpoint stays where it is.
        self.assertIn("missing", entry["problem"])
        self.assertIsNone(result["table"]["be10:W1"]["change_bp"])  # A derived measure needs both parts.
        self.assertIsNotNone(result["table"]["n10:W5"]["change_bp"])
        self.assertEqual(check(result, "R1", "10", "W1")["outcome"], "not_evaluable")
        self.assertEqual(check(result, "R1", "10", "W5")["outcome"] != "not_evaluable", True)


class ReferenceTests(unittest.TestCase):
    def test_reference_windows_precede_the_window_and_match_its_span(self):
        built = grid()
        entry = rules.evaluate(built, EVENT)["table"]["n2:W5"]
        reference = entry["reference"]
        self.assertEqual((entry["span"], reference["candidates"], reference["eligible"]), (6, 250, 250))
        self.assertEqual(reference["last_end"], B1.isoformat())  # Ends on or before the window's start.
        start = built.index[B1]
        expected = [built.change("n2", j - 6, j) for j in range(start - 249, start + 1)]
        self.assertEqual(reference["first_end"], built.dates[start - 249].isoformat())
        measured = Decimal(entry["change_bp"])
        smaller = sum(abs(item) < abs(measured) for item in expected)
        equal = sum(abs(item) == abs(measured) for item in expected)
        self.assertEqual((reference["smaller"], reference["equal"]), (smaller, equal))
        self.assertEqual(Decimal(reference["rank"]), ((Decimal(smaller) + Decimal(equal) / 2) / 250).quantize(
            Decimal("0.0001")))

    def test_ties_count_half(self):
        steady = grid(value=lambda series_id, day: f"{1 + SESSIONS.index(day) / 100:.2f}")  # +1 bp every session.
        entry = rules.evaluate(steady, EVENT)["table"]["n10:W1"]
        self.assertEqual((entry["change_bp"], entry["reference"]["equal"], entry["reference"]["rank"]),
                         ("2", 250, "0.5000"))

    def test_too_few_usable_reference_windows_leave_no_rank(self):
        start = SESSIONS.index(B1)
        gaps = {(N2, SESSIONS[i]): None for i in range(start - 249, start - 100, 2)}  # Many missing values.
        entry = rules.evaluate(grid(gaps), EVENT)["table"]["n2:W1"]
        self.assertIsNotNone(entry["change_bp"])
        self.assertNotIn("rank", entry["reference"])
        self.assertLess(entry["reference"]["eligible"], rules.MINIMUM_ELIGIBLE)
        self.assertIn("at least 200", entry["problem"])


class RuleTests(unittest.TestCase):
    def test_offsetting_components_hidden_by_an_ordinary_nominal_change(self):
        built = grid({(N10, A1): pattern(N10, B1), (R10, A1): at(B1, R10, "0.30")})  # Nominal 0, real +30, be -30.
        result = rules.evaluate(built, EVENT)
        self.assertEqual(check(result, "R1", "10", "W1")["outcome"], "met")
        table = result["table"]
        self.assertEqual((table["n10:W1"]["change_bp"], table["r10:W1"]["change_bp"], table["be10:W1"]["change_bp"]),
                         ("0", "30", "-30"))
        same_sign = rules.evaluate(grid({(N10, A1): at(B1, N10, "0.60"), (R10, A1): at(B1, R10, "0.30")}), EVENT)
        self.assertEqual(check(same_sign, "R1", "10", "W1")["outcome"], "not_met")

    def test_one_component_dominates_and_the_share_is_guarded(self):
        built = grid({(N10, A5): at(B1, N10, "0.40"), (R10, A5): at(B1, R10, "0.38")})  # Real +38, be +2.
        found = check(rules.evaluate(built, EVENT), "R2", "10", "W5")
        self.assertEqual((found["outcome"], found["detail"]), ("met", {"dominant": "inflation-indexed",
                                                                        "share": "0.95"}))
        even = check(rules.evaluate(grid({(N10, A5): at(B1, N10, "0.40"), (R10, A5): at(B1, R10, "0.20")}), EVENT),
                     "R2", "10", "W5")
        self.assertEqual((even["outcome"], even["detail"]["share"]), ("not_met", "0.50"))
        flat = check(rules.evaluate(grid({(N10, A5): pattern(N10, B1), (R10, A5): pattern(R10, B1)}), EVENT),
                     "R2", "10", "W5")
        self.assertEqual(flat["outcome"], "not_met")  # A zero nominal change has no dominant part to report.

    def test_slope_and_timing(self):
        slope = rules.evaluate(grid({(N2, A1): at(B1, N2, "0.40"), (N10, A1): pattern(N10, B1)}), EVENT)
        self.assertEqual(check(slope, "R3", None, "W1")["outcome"], "met")
        before = rules.evaluate(grid({(N2, B6): at(B1, N2, "-0.40"), (N2, A5): pattern(N2, B1)}), EVENT)
        found = check(before, "R4", "n2", None)
        self.assertEqual((found["outcome"], found["detail"]), ("met", {"direction": "before"}))
        after = rules.evaluate(grid({(N3M, B6): pattern(N3M, B1), (N3M, A5): at(B1, N3M, "0.40")}), EVENT)
        self.assertEqual(check(after, "R4", "n3m", None)["detail"], {"direction": "after"})

    def test_every_occasion_runs_the_same_twelve_checks(self):
        result = rules.evaluate(grid(), EVENT)
        self.assertEqual(len(result["checks"]), 12)
        self.assertEqual([rules.check_key(item) for item in result["checks"]],
                         [f"{rule}:{subject}:{window}" for rule, subject, window in rules.CHECKS])


class InputTests(unittest.TestCase):
    def test_inputs_cover_reference_history_and_windows_exactly(self):
        built = grid()
        observed = rules.inputs(built, EVENT)
        start = built.index[B6] - 249 - 5
        self.assertEqual([observed[N2][0][0], observed[N2][-1][0]], [built.dates[start].isoformat(), "2026-09-23"])
        self.assertEqual(set(observed), set(rules.YIELDS))
        changed = grid({(N2, built.dates[start]): "9.99"})  # A value inside the inputs changes their SHA-256.
        self.assertNotEqual(rules.inputs_sha256(rules.inputs(changed, EVENT)), rules.inputs_sha256(observed))
        outside = grid({(N2, built.dates[start - 1]): "9.99"})  # One just before them does not.
        self.assertEqual(rules.inputs_sha256(rules.inputs(outside, EVENT)), rules.inputs_sha256(observed))

    def test_comparison_sessions_are_seeded_and_skip_event_windows(self):
        built = grid()
        first = rules.comparison(built, {EVENT}, "seed-a", 20, date(2025, 3, 3), date(2026, 9, 1))
        again = rules.comparison(built, {EVENT}, "seed-a", 20, date(2025, 3, 3), date(2026, 9, 1))
        other = rules.comparison(built, {EVENT}, "seed-b", 20, date(2025, 3, 3), date(2026, 9, 1))
        self.assertEqual(first, again)
        self.assertNotEqual(first["sessions"], other["sessions"])
        self.assertEqual(len(first["sessions"]), 20)
        for day in first["sessions"]:
            points = rules.endpoints(built, date.fromisoformat(day))
            self.assertFalse(built.dates[points["B6"]] <= EVENT <= built.dates[points["A5"]])
        self.assertTrue(all(item["evaluable"] <= 20 and item["met"] <= item["evaluable"]
                            for item in first["checks"].values()))
        self.assertEqual(first["any"]["evaluable"], 20)


if __name__ == "__main__":
    unittest.main()

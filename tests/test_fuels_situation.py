import unittest
from datetime import date, timedelta
from fractions import Fraction as F

from second_order.fuels_situation import LABELS, STALE_DAYS, month_before, situation, split_label

ROLES = ("brent", "wti", "gasoline", "diesel", "henry_hub")


def build(days, brent=80, gasoline=F(21, 10), diesel=F(25, 10)):
    """Synthetic values that change a little on each given date."""
    inputs = {"brent": {}, "gasoline": {}, "diesel": {}}
    for i, day in enumerate(days):
        inputs["brent"][day] = F(brent) + F(i, 4)
        inputs["gasoline"][day] = gasoline + F(i, 50)
        inputs["diesel"][day] = diesel + F(i, 40) * (-1) ** i
    return inputs


def latest_all(day, **over):
    latest = {role: day for role in ROLES}
    latest.update(over)
    return latest


def daily(start, end):
    days, d = [], start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def windows_of(inputs, latest, retrieved):
    """The windows of a situation by id, with every role's latest observation on `latest`."""
    return {w["id"]: w for w in situation(inputs, latest_all(latest), retrieved)["windows"]}


class SituationTests(unittest.TestCase):
    def test_the_split_is_an_identity_and_its_parts_add_up(self):
        days = daily(date(2026, 9, 20), date(2026, 11, 3))
        s = situation(build(days), latest_all(days[-1]), date(2026, 11, 6))
        computed = [w for w in s["windows"] if w["state"] == "computed"]
        self.assertEqual(len(computed), 3)
        for w in computed:
            p = {k: F(w["split"][k]["value"]) for k in ("crude", "crack", "basket", "gasoline_part", "diesel_part")}
            self.assertEqual(p["crude"] + p["crack"], p["basket"])
            self.assertEqual(p["gasoline_part"] + p["diesel_part"], p["basket"])
            self.assertEqual(p["basket"], F(w["rows"]["basket"]["change"]["value"]))
            self.assertIn(w["split"]["label"], LABELS)

    def test_labels(self):
        self.assertEqual(split_label(F(0), F(0)), "unchanged")
        self.assertEqual(split_label(F(2), F(-1)), "offsetting")
        self.assertEqual(split_label(F(2), F(1)), "mostly_crude")
        self.assertEqual(split_label(F(1), F(2)), "mostly_crack")
        self.assertEqual(split_label(F(1), F(1)), "both")
        self.assertEqual(split_label(F(0), F(-3)), "mostly_crack")
        self.assertEqual(split_label(F(-3), F(0)), "mostly_crude")

    def test_zero_negative_and_positive_cracks_are_handled_alike(self):
        # with gasoline and diesel at 2 the basket is 84, so Brent 84, 200 and 50 give crack 0, negative, positive
        for brent_to in (F(84), F(200), F(50)):
            d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
            inputs = {"brent": {d1: F(80), d2: brent_to},
                      "gasoline": {d1: F(2), d2: F(2)}, "diesel": {d1: F(2), d2: F(2)}}
            s = situation(inputs, latest_all(d2), date(2026, 11, 4))
            row = s["windows"][0]["rows"]["crack"]
            self.assertIsNone(row["pct"])
            self.assertEqual(F(row["to"]["value"]), 84 - brent_to)
            self.assertEqual(F(row["change"]["value"]), F(row["to"]["value"]) - F(row["from"]["value"]))

    def test_a_week_with_a_gap_before_its_target_is_unavailable(self):
        days = daily(date(2026, 10, 1), date(2026, 10, 20)) + [date(2026, 10, 28), date(2026, 10, 29),
                                                              date(2026, 10, 30), date(2026, 11, 2),
                                                              date(2026, 11, 3)]
        s = situation(build(days), latest_all(date(2026, 11, 3)), date(2026, 11, 6))
        by = {w["id"]: w for w in s["windows"]}
        self.assertEqual(by["week"]["state"], "unavailable")
        self.assertEqual(by["week"]["reason"], "No common observation within 3 days before 27 Oct 2026")
        self.assertEqual(by["week"]["target"], "2026-10-27")
        self.assertIsNone(by["week"]["rows"])
        self.assertIsNone(by["week"]["split"])
        self.assertEqual(by["previous"]["state"], "computed")
        self.assertEqual(by["previous"]["from"], "2026-11-02")
        self.assertEqual(by["month"]["target"], "2026-10-03")
        self.assertEqual(by["month"]["state"], "computed")

    def test_a_week_within_tolerance_is_computed_and_uses_the_earlier_date(self):
        days = [date(2026, 10, 24), date(2026, 10, 30), date(2026, 11, 3)]
        s = situation(build(days), latest_all(date(2026, 11, 3)), date(2026, 11, 4))
        week = {w["id"]: w for w in s["windows"]}["week"]
        self.assertEqual((week["state"], week["from"], week["to"]), ("computed", "2026-10-24", "2026-11-03"))
        self.assertEqual(week["target"], "2026-10-27")

    def test_a_week_four_days_short_of_its_target_is_unavailable(self):
        # 23 Oct is four days before the 27 Oct target: one day past the three-day tolerance.
        days = [date(2026, 10, 23)] + daily(date(2026, 10, 28), date(2026, 11, 3))
        week = windows_of(build(days), date(2026, 11, 3), date(2026, 11, 4))["week"]
        self.assertEqual((week["state"], week["from"], week["rows"], week["split"]), ("unavailable", None, None, None))
        self.assertEqual(week["reason"], "No common observation within 3 days before 27 Oct 2026")

    def test_a_month_five_days_short_is_computed_and_six_days_short_is_unavailable(self):
        latest = date(2026, 11, 3)  # the month target is 3 Oct 2026
        five = [date(2026, 9, 28)] + daily(date(2026, 10, 20), latest)
        month = windows_of(build(five), latest, date(2026, 11, 4))["month"]
        self.assertEqual((month["state"], month["target"], month["from"]), ("computed", "2026-10-03", "2026-09-28"))
        six = [date(2026, 9, 27)] + daily(date(2026, 10, 20), latest)
        month = windows_of(build(six), latest, date(2026, 11, 4))["month"]
        self.assertEqual((month["state"], month["from"]), ("unavailable", None))
        self.assertEqual(month["reason"], "No common observation within 5 days before 3 Oct 2026")

    def test_a_missing_value_inside_a_series_excludes_that_date(self):
        days = [date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3)]
        inputs = build(days)
        inputs["gasoline"][date(2026, 11, 2)] = None
        s = situation(inputs, latest_all(date(2026, 11, 3)), date(2026, 11, 4))
        previous = s["windows"][0]
        self.assertEqual((s["date"], previous["state"], previous["from"]), ("2026-11-03", "computed", "2026-10-30"))
        inputs["diesel"][date(2026, 11, 3)] = None
        s = situation(inputs, latest_all(date(2026, 11, 3)), date(2026, 11, 4))
        self.assertEqual((s["date"], s["windows"][0]["state"]), ("2026-10-30", "unavailable"))

    def test_the_leap_year_clamp_end_to_end(self):
        leap = daily(date(2024, 2, 20), date(2024, 3, 31))
        month = windows_of(build(leap), date(2024, 3, 31), date(2024, 4, 1))["month"]
        self.assertEqual((month["target"], month["state"], month["from"]), ("2024-02-29", "computed", "2024-02-29"))
        plain = daily(date(2026, 2, 20), date(2026, 3, 31))
        month = windows_of(build(plain), date(2026, 3, 31), date(2026, 4, 1))["month"]
        self.assertEqual((month["target"], month["state"], month["from"]), ("2026-02-28", "computed", "2026-02-28"))

    def test_month_window_reason_uses_five_days(self):
        days = [date(2026, 9, 1), date(2026, 10, 30), date(2026, 11, 3)]
        s = situation(build(days), latest_all(date(2026, 11, 3)), date(2026, 11, 4))
        month = {w["id"]: w for w in s["windows"]}["month"]
        self.assertEqual(month["reason"], "No common observation within 5 days before 3 Oct 2026")

    def test_the_month_target_clamps(self):
        self.assertEqual(month_before(date(2026, 3, 31)), date(2026, 2, 28))
        self.assertEqual(month_before(date(2024, 3, 31)), date(2024, 2, 29))
        self.assertEqual(month_before(date(2026, 1, 15)), date(2025, 12, 15))

    def test_percent_uses_exact_values_and_skips_non_positive_bases(self):
        d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
        inputs = {"brent": {d1: F(8), d2: F(81, 10)},
                  "gasoline": {d1: F(2), d2: F(2)}, "diesel": {d1: F(2), d2: F(2)}}
        rows = situation(inputs, latest_all(d2), date(2026, 11, 4))["windows"][0]["rows"]
        # 8 to 8.1 is exactly 1.25 percent; half-even to one place is 1.2
        self.assertEqual(rows["brent"]["pct"]["shown"], "1.2")
        inputs["brent"][d1] = F(0)
        rows = situation(inputs, latest_all(d2), date(2026, 11, 4))["windows"][0]["rows"]
        self.assertIsNone(rows["brent"]["pct"])
        inputs["brent"][d1] = F(-1)
        rows = situation(inputs, latest_all(d2), date(2026, 11, 4))["windows"][0]["rows"]
        self.assertIsNone(rows["brent"]["pct"])
        self.assertEqual(rows["gasoline"]["pct"]["shown"], "0.0")

    def test_shown_places(self):
        d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
        inputs = {"brent": {d1: F(80), d2: F(8123, 100)},
                  "gasoline": {d1: F(2), d2: F(2123, 1000)}, "diesel": {d1: F(2), d2: F(2)}}
        rows = situation(inputs, latest_all(d2), date(2026, 11, 4))["windows"][0]["rows"]
        self.assertEqual(rows["brent"]["to"]["shown"], "81.23")
        self.assertEqual(rows["gasoline"]["to"]["shown"], "2.123")
        self.assertEqual(rows["diesel"]["to"]["shown"], "2.000")

    def test_stale_and_newer(self):
        days = daily(date(2026, 10, 1), date(2026, 10, 20))
        latest = latest_all(date(2026, 10, 20), brent=date(2026, 10, 22), wti=None, henry_hub=None)
        s = situation(build(days), latest, date(2026, 11, 6))
        self.assertEqual((s["age_days"], s["stale"]), (17, True))
        self.assertEqual(s["newer"], [{"role": "brent", "date": "2026-10-22"}])
        self.assertEqual(s["date"], "2026-10-20")
        self.assertEqual(STALE_DAYS, 10)
        fresh = situation(build(days), latest_all(date(2026, 10, 20)), date(2026, 10, 30))
        self.assertEqual((fresh["age_days"], fresh["stale"], fresh["newer"]), (10, False, []))

    def test_no_retrieval_date(self):
        days = daily(date(2026, 10, 1), date(2026, 10, 5))
        s = situation(build(days), latest_all(days[-1]), None)
        self.assertEqual((s["age_days"], s["stale"]), (None, False))

    def test_withheld_without_inputs(self):
        s = situation(None, latest_all(None), date(2026, 11, 6))
        self.assertEqual((s["state"], s["windows"], s["date"]), ("withheld", [], None))
        self.assertTrue(s["problem"])

    def test_withheld_with_no_common_date(self):
        inputs = {"brent": {date(2026, 11, 2): F(80)}, "gasoline": {date(2026, 11, 3): F(2)},
                  "diesel": {date(2026, 11, 3): F(2)}}
        self.assertEqual(situation(inputs, latest_all(None), None)["state"], "withheld")

    def test_one_common_date_has_no_windows(self):
        d = date(2026, 11, 3)
        inputs = {"brent": {d: F(80)}, "gasoline": {d: F(2)}, "diesel": {d: F(2)}}
        s = situation(inputs, latest_all(d), date(2026, 11, 4))
        self.assertEqual(s["state"], "computed")
        self.assertEqual([w["id"] for w in s["windows"]], ["previous", "week", "month"])
        self.assertTrue(all(w["state"] == "unavailable" for w in s["windows"]))
        self.assertEqual(s["windows"][0]["reason"], "There is no earlier common observation")
        self.assertIsNone(s["windows"][0]["from"])


if __name__ == "__main__":
    unittest.main()

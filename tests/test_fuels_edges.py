"""The fuels page's two edge cases, on SYNTHETIC worlds (tests/fuels_fakes.py) in temporary folders.

(a) A change too small to show: its exact value and the split's label stay as computed; the note's filled prose says
which way it moved and that it is under the last shown place, and keeps a true zero apart.
(b) A series far behind the others: its price stays on the page, verified, with its own date and how far behind it
is; whatever is computed from it is withheld, prices from different dates are never combined and nothing is filled
in. A snapshot or a source that fails verification still withholds as before."""
from datetime import date, timedelta
from fractions import Fraction as F
import json
import shutil
import unittest

import fuels_fakes
from test_fuels_api import Fuels
from second_order import fuels_crack, fuels_notes, fuels_view
from second_order.fuels_situation import situation

ROLES = ("brent", "wti", "gasoline", "diesel", "henry_hub")
START, END = date(2026, 10, 27), date(2026, 11, 3)  # a week apart: the week window and the previous one coincide


def two_days(brent, gasoline, diesel):
    """Inputs on START and END: each argument is (start value, end value)."""
    return {name: {START: F(pair[0]), END: F(pair[1])}
            for name, pair in (("brent", brent), ("gasoline", gasoline), ("diesel", diesel))}


def week(inputs):
    s = situation(inputs, {role: END for role in ROLES}, date(2026, 11, 6))
    return next(w for w in s["windows"] if w["id"] == "week")


class SmallChangeArithmetic(unittest.TestCase):
    """The exact values and the label are computed as before; only the display changes."""

    def test_a_small_fall_in_the_crack_keeps_its_exact_value_and_the_offsetting_label(self):
        # Brent +0.06; basket 14 x 0.004 = +0.056; so the crack moves -0.004, shown as 0.00.
        w = week(two_days(("80", "80.06"), ("2.5", "2.5"), ("3", "3.004")))
        split = w["split"]
        self.assertEqual(split["crack"], {"value": "-0.004", "shown": "0.00"})
        self.assertEqual(split["crude"], {"value": "0.06", "shown": "0.06"})
        self.assertEqual(split["label"], "offsetting")
        self.assertEqual(F(split["crude"]["value"]) + F(split["crack"]["value"]), F(split["basket"]["value"]))

    def test_a_small_rise_in_the_crack_keeps_its_exact_value_and_the_offsetting_label(self):
        w = week(two_days(("80", "79.94"), ("2.5", "2.5"), ("3", "2.996")))
        self.assertEqual(w["split"]["crack"], {"value": "0.004", "shown": "0.00"})
        self.assertEqual(w["split"]["label"], "offsetting")

    def test_a_true_zero_is_exactly_zero(self):
        w = week(two_days(("80", "80.07"), ("2.5", "2.5"), ("3", "3.005")))  # 14 x 0.005 = 0.07 = Brent's move
        self.assertEqual(w["split"]["crack"], {"value": "0", "shown": "0.00"})
        self.assertEqual(w["split"]["label"], "mostly_crude")

    def test_rounding_boundaries_are_half_even_at_the_last_shown_place(self):
        cases = {"0.005": "0.00", "-0.005": "0.00", "0.0051": "0.01", "-0.0051": "-0.01", "0.015": "0.02",
                 "-0.015": "-0.02", "0.025": "0.02", "0.0049": "0.00", "-0.0049": "0.00"}
        for value, shown in cases.items():
            self.assertEqual(fuels_crack.shown(F(value), 2), shown, value)
        self.assertEqual(fuels_crack.shown(F("-0.0005"), 3), "0.000")
        self.assertEqual(fuels_crack.shown(F("0.0006"), 3), "0.001")


class SmallChangeProse(unittest.TestCase):
    """A note's placeholders: the direction from the exact value, the size as under the last shown place."""

    def values(self, inputs):
        s = situation(inputs, {role: END for role in ROLES}, date(2026, 11, 6))
        return fuels_notes.window_values(s, "week")

    def test_a_change_under_the_last_shown_place_says_which_way_and_less_than(self):
        # Brent +0.046 on 100 (0.046%, shown 0.0); diesel +0.003; the crack 14 x 0.003 - 0.046 = -0.004.
        v = self.values(two_days(("100", "100.046"), ("2.5", "2.5"), ("3", "3.003")))
        self.assertEqual((v["week_crack_move"], v["week_crack_change"]), ("fell", "less than $0.01 a barrel"))
        self.assertEqual(v["week_brent_pct"], "less than 0.1%")
        self.assertEqual(v["week_basket_pct"], "less than 0.1%")
        self.assertEqual(v["week_diesel_pct"], "0.1%")

    def test_a_true_zero_stays_unchanged_and_is_not_called_small(self):
        v = self.values(two_days(("100", "100.046"), ("2.5", "2.5"), ("3", "3.003")))
        self.assertEqual((v["week_gasoline_move"], v["week_gasoline_change"]), ("was unchanged", "$0.000 a gallon"))
        self.assertEqual(v["week_gasoline_pct"], "0.0%")
        self.assertEqual(v["week_gasoline_part"], "$0.00 a barrel")

    def test_a_small_part_of_the_split_keeps_its_sign(self):
        # gasoline -0.0001 a gallon: its part is 28 x -0.0001 = -0.0028 a barrel, shown 0.00.
        fall = self.values(two_days(("80", "80.5"), ("2.5", "2.4999"), ("3", "3.1")))
        self.assertEqual(fall["week_gasoline_part"], "a fall of less than $0.01 a barrel")
        self.assertEqual(fall["week_gasoline_change"], "less than $0.001 a gallon")
        rise = self.values(two_days(("80", "80.5"), ("2.5", "2.5001"), ("3", "3.1")))
        self.assertEqual(rise["week_gasoline_part"], "a rise of less than $0.01 a barrel")
        self.assertEqual(rise["week_diesel_part"], "+$1.40 a barrel")

    def test_brents_change_since_the_previous_observation_says_which_way(self):
        def barrel(brent_change):
            return {"previous_date": "2026-11-02", "change": {"brent": brent_change}}
        self.assertEqual(fuels_notes._change_text(barrel({"value": "-0.004", "shown": "0.00"})),
                         "down less than $0.01 since 2 Nov 2026")
        self.assertEqual(fuels_notes._change_text(barrel({"value": "0.004", "shown": "0.00"})),
                         "up less than $0.01 since 2 Nov 2026")
        self.assertEqual(fuels_notes._change_text(barrel({"value": "0", "shown": "0.00"})),
                         "unchanged since 2 Nov 2026")
        self.assertEqual(fuels_notes._change_text(barrel({"value": "-0.96", "shown": "-0.96"})),
                         "−$0.96 since 2 Nov 2026")


class BehindLimit(unittest.TestCase):
    def test_a_series_is_behind_only_when_more_than_ten_days_older_than_the_newest(self):
        newest = date(2026, 11, 3)
        lags = fuels_view.behind({"brent": newest, "wti": newest - timedelta(days=10),
                                  "diesel": newest - timedelta(days=11), "henry_hub": None})
        self.assertIsNone(lags["brent"])
        self.assertIsNone(lags["wti"])
        self.assertEqual(lags["diesel"], {"days": 11, "newest": "2026-11-03"})
        self.assertIsNone(lags["henry_hub"])
        self.assertEqual(fuels_view.behind({"brent": None}), {"brent": None})


class Behind(Fuels):
    def lagging(self, role: str, last: date = fuels_fakes.YEAR_BEHIND, **options) -> dict:
        shutil.rmtree(self.snapshots)
        fuels_fakes.write_snapshot(self.snapshots, behind={role: last}, **options)
        return self.get()

    @staticmethod
    def row(v: dict, role: str) -> dict:
        return next(s for s in v["series"] if s["role"] == role)

    def assertKept(self, row: dict, last: str = "2025-11-03"):
        """A verified price with its own date and a history that ends there: nothing after it is filled in."""
        self.assertEqual((row["state"], row["kind"], row["problem"]), ("verified", "published", None))
        self.assertEqual(row["latest"]["date"], last)
        self.assertEqual(row["history"][-1][0], last)
        self.assertTrue(all(day <= last for day, _ in row["history"]))

    def test_wti_or_henry_hub_a_year_behind_keeps_its_price_and_date_and_leaves_the_rest_as_it_was(self):
        normal = self.get()
        for role in ("wti", "henry_hub"):
            with self.subTest(role):
                v = self.lagging(role)
                row = self.row(v, role)
                self.assertKept(row)
                self.assertEqual(row["behind"], {"days": 365, "newest": "2026-11-03"})
                for other in ROLES:
                    if other != role:
                        self.assertIsNone(self.row(v, other)["behind"], other)
                self.assertEqual(v["barrel"], normal["barrel"])
                self.assertEqual(v["crack_history"], normal["crack_history"])
                self.assertEqual(v["situation"], normal["situation"])
                coverage = next(c for c in v["coverage"] if c["id"] == role)
                self.assertEqual(coverage["state"], "verified")

    def test_a_barrel_input_a_year_behind_withholds_the_barrel_the_crack_and_situation_now(self):
        for role in ("brent", "gasoline", "diesel"):
            with self.subTest(role):
                v = self.lagging(role)
                row = self.row(v, role)
                self.assertKept(row)
                self.assertEqual(row["behind"], {"days": 365, "newest": "2026-11-03"})
                for other in ROLES:
                    if other != role:
                        self.assertKept(self.row(v, other), "2026-11-03")
                        self.assertIsNone(self.row(v, other)["behind"])
                barrel = v["barrel"]
                self.assertEqual(barrel["state"], "withheld")
                for field in ("date", "previous_date", "inputs", "previous", "basket", "crack", "change",
                              "published_on"):
                    self.assertIsNone(barrel[field], field)
                self.assertIn(row["label"], barrel["problem"])
                self.assertIn("3 Nov 2025", barrel["problem"])
                self.assertIn("365 days", barrel["problem"])
                self.assertIn("never combined", barrel["problem"])
                self.assertEqual(v["crack_history"], [])
                self.assertEqual((v["situation"]["state"], v["situation"]["windows"]), ("withheld", []))

    def test_a_week_behind_is_not_behind_and_the_barrel_stays_on_the_latest_common_date(self):
        v = self.lagging("diesel", date(2026, 10, 27))
        self.assertIsNone(self.row(v, "diesel")["behind"])
        self.assertEqual((v["barrel"]["state"], v["barrel"]["date"]), ("computed", "2026-10-27"))
        self.assertEqual(v["situation"]["newer"], [{"role": role, "date": "2026-11-03"}
                                                   for role in ("brent", "wti", "gasoline", "henry_hub")])

    def test_an_old_snapshot_whose_series_are_all_equally_old_has_none_behind(self):
        shutil.rmtree(self.snapshots)
        fuels_fakes.write_snapshot(self.snapshots, retrieved=fuels_fakes.RETRIEVED + timedelta(days=60))
        v = self.get()
        self.assertTrue(all(row["behind"] is None for row in v["series"]))
        self.assertEqual(v["barrel"]["state"], "computed")
        self.assertTrue(v["situation"]["stale"])

    def test_a_snapshot_that_no_longer_verifies_still_withholds_every_value(self):
        self.lagging("diesel")
        self.edit_snapshot(lambda data: data.update(retrieved_at="2026-11-07T00:00:00+00:00"))
        v = self.get()
        self.assertEqual(v["snapshot"]["state"], "changed")
        for row in v["series"]:
            self.assertEqual((row["state"], row["latest"], row["history"], row["behind"]),
                             ("missing", None, [], None), row["role"])
        self.assertEqual(v["barrel"]["state"], "withheld")
        self.assertEqual(v["barrel"]["problem"], "No data for brent, gasoline, diesel.")

    def test_a_refused_series_stays_refused_beside_a_series_behind(self):
        v = self.lagging("wti", rows={"EER_EPMRU_PF4_Y35NY_DPG": {"units": "$/BBL"}})
        gasoline = self.row(v, "gasoline")
        self.assertEqual((gasoline["state"], gasoline["latest"], gasoline["behind"]), ("refused", None, None))
        self.assertEqual(self.row(v, "wti")["behind"], {"days": 365, "newest": "2026-11-03"})
        self.assertEqual((v["barrel"]["state"], v["barrel"]["problem"]), ("withheld", "No data for gasoline."))

    def test_a_note_bound_to_a_snapshot_with_a_barrel_input_behind_is_unbound(self):
        """Without the rule, its figures would come from a barrel a year older than the other prices."""
        self.lagging("diesel")
        snapshot_id = self.get()["snapshot"]["id"]
        note = fuels_fakes.analysis_note(snapshot_id, "2025-11-03", number=2)
        fuels_notes.check_note(note, 2)
        (self.content / "notes" / "situation-0002.json").write_text(json.dumps(note), encoding="utf-8")
        shown = self.get()["note"]
        self.assertEqual(shown["state"], "unbound")
        self.assertEqual(shown["problem"], "The snapshot this note was written for has no complete barrel.")


if __name__ == "__main__":
    unittest.main()

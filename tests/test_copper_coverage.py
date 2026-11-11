"""The coverage engine (copper_coverage) on SYNTHETIC copies of the published values: the design's worked example,
the published non-additivity, hybrids, perturbations, withholding and every refusal, with mutation tests showing that
each refusal test fails without its guard."""
from decimal import Decimal
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import copper_fakes
from second_order import copper_coverage as cc, copper_inputs, copper_producers as cp
from second_order.thesis_rules import ThesisRefused

COMMITTED = Path(__file__).resolve().parent.parent / "content" / "tools" / "copper-coverage"
SET_A = {"ev": {"source": "scenario", "scenario": "cps"},
         "networks": {"source": "technology_case", "scenario": "steps"},
         "mine": {"source": "total", "kt": "-294.8350405", "reference": "ptfi-sales-change"}}


def synthetic_values() -> dict[str, Decimal]:
    with tempfile.TemporaryDirectory() as temp:
        root = copper_fakes.write_sources(Path(temp))
        catalog = copper_inputs.check_catalog(copper_fakes.catalog(root, "coverage"))
        _, states = copper_inputs.check_items(catalog, root)
        return copper_inputs.verified_values(catalog, states)


VALUES = synthetic_values()


def computed_items(node):
    """Every computed item (it names an equation) anywhere in a reply."""
    if isinstance(node, dict):
        if "equation" in node:
            yield node
        for value in node.values():
            yield from computed_items(value)
    elif isinstance(node, list):
        for value in node:
            yield from computed_items(value)


class WorkedExample(unittest.TestCase):
    def test_steps_2035(self):
        base = cc.baseline(VALUES, "steps", "2035")
        coverage = base["coverage"]
        self.assertEqual((coverage["residual"]["value"], coverage["residual"]["shown"]), ("12789", "12,789"))
        self.assertEqual(coverage["share_pct"]["shown"], "38.2")
        self.assertEqual(base["base"]["residual"]["value"], "4548")
        self.assertEqual(base["base"]["share_pct"]["shown"], "16.4")
        self.assertEqual(base["epsilon"]["value"], "-2.0132")
        decomposition = base["decomposition"]
        self.assertEqual(decomposition["residual_change"]["value"], "8241")
        self.assertEqual(decomposition["mine_change"]["value"], "-2494")
        rows = {row["line"]: row["change"]["value"] for row in decomposition["demand_rows"]}
        self.assertEqual(rows, {"solar": "194", "wind": "192", "other-low-emission": "50.2", "ev": "1767",
                                "grid-storage": "213", "networks": "1905", "hydrogen": "0.00735", "energy": "4361",
                                "other-uses": "1386", "total": "5747"})
        self.assertEqual(decomposition["epsilon_change"]["value"], "39.79265")
        self.assertEqual(decomposition["delta_change"]["value"], "0")

    def test_the_decomposition_adds_up_exactly(self):
        for scenario in cc.SCENARIOS:
            for year in cc.YEARS:
                decomposition = cc.baseline(VALUES, scenario, year)["decomposition"]
                rows = {row["line"]: Decimal(row["change"]["value"]) for row in decomposition["demand_rows"]}
                components = sum(rows[key] for key in cc.COMPONENTS)
                self.assertEqual(components + Decimal(decomposition["epsilon_change"]["value"]), rows["energy"])
                self.assertEqual(rows["energy"] + rows["other-uses"] + Decimal(decomposition["delta_change"]["value"]),
                                 rows["total"])
                self.assertEqual(rows["total"] - Decimal(decomposition["mine_change"]["value"]),
                                 Decimal(decomposition["residual_change"]["value"]))

    def test_other_scenarios(self):
        for scenario, residual, change in (("cps", "11626", "7078"), ("hd", "13561", "9013")):
            base = cc.baseline(VALUES, scenario, "2035")
            self.assertEqual(base["coverage"]["residual"]["value"], residual)
            self.assertEqual(base["decomposition"]["residual_change"]["value"], change)

    def test_assumption_set_a_keeps_exact_values(self):
        """The reference magnitude is 650 million pounds x 0.45359237 = 294.8350405 kt exactly; the design's
        12,622.835 is its display, and the exact value is carried into every later step."""
        result = cc.assess(VALUES, "steps", "2035", SET_A)
        self.assertEqual(result["demand"]["value"], "33061")
        self.assertEqual(result["mine"]["value"], "20438.1649595")
        self.assertEqual((result["residual"]["value"], result["residual"]["shown"], result["residual"]["rounded"]),
                         ("12622.8350405", "12,622.835", True))
        self.assertEqual(result["share_pct"]["shown"], "38.2")
        self.assertEqual(result["residual_change"]["value"], "8074.8350405")
        self.assertEqual([flag["id"] for flag in result["flags"]], ["hybrid", "technology_case",
                                                                    "reference_magnitude"])

    def test_a_rounded_magnitude_is_refused(self):
        """Typing the shown 294.835 as the tagged reference is refused: a rounded number never feeds arithmetic."""
        rounded = {**SET_A, "mine": {"source": "total", "kt": "-294.835", "reference": "ptfi-sales-change"}}
        with self.assertRaises(ThesisRefused) as raised:
            cc.assess(VALUES, "steps", "2035", rounded)
        self.assertIn("294.8350405", str(raised.exception))
        untagged = cc.assess(VALUES, "steps", "2035", {"mine": {"source": "total", "kt": "-294.835"}})
        self.assertEqual(untagged["residual"]["value"], "13083.835")  # An untagged user change stays as entered.
        self.assertEqual(untagged["flags"], [])

    def test_hybrid_overshoots_the_published_total(self):
        result = cc.assess(VALUES, "steps", "2035", {"ev": {"source": "scenario", "scenario": "hd"},
                                                     "networks": {"source": "scenario", "scenario": "hd"}})
        self.assertEqual(result["demand"]["value"], "34694")
        self.assertEqual(cc.baseline(VALUES, "hd", "2035")["demand"][-1]["value"], "34294")
        self.assertEqual([flag["id"] for flag in result["flags"]], ["hybrid"])
        same = cc.assess(VALUES, "steps", "2035", {"ev": {"source": "scenario", "scenario": "steps"}})
        self.assertEqual(same["flags"], [])
        self.assertEqual(same["residual"]["value"], "12789")

    def test_perturbations_around_steps_2035(self):
        rows = cc.baseline(VALUES, "steps", "2035")["perturbations"]
        self.assertEqual([(row["control"], row["kind"]) for row in rows],
                         [("ev", "published_scenario_value"), ("networks", "published_scenario_value"),
                          ("networks", "published_technology_case"), ("mine", "reference_magnitude"),
                          ("joint", "published_totals")])
        effects = [[case["effect"]["value"] for case in row["cases"]] for row in rows if "effect" in row["cases"][0]]
        self.assertEqual(effects, [["-415", "697"], ["-51", "475"], ["-46"], ["-1163", "772"]])
        magnitudes = [case["magnitude"]["value"] for case in rows[3]["cases"]]
        self.assertEqual(magnitudes, ["294.8350405", "54.4"])
        text = json.dumps(rows).lower()
        for word in ("probab", "likel", "most important", "rank", "interval"):
            self.assertNotIn(word, text)

    def test_cps_has_no_technology_case(self):
        rows = cc.baseline(VALUES, "cps", "2035")["perturbations"]
        self.assertNotIn("published_technology_case", [row["kind"] for row in rows])

    def test_user_declared_mine_change_is_its_own_row(self):
        result = cc.assess(VALUES, "steps", "2035", {"mine": {"source": "total", "kt": "100"}})
        rows = [row for row in result["perturbations"] if row["kind"] == "user_declared"]
        self.assertEqual(rows[0]["cases"][0]["effect"]["value"], "-100")
        factors = cc.assess(VALUES, "steps", "2035", {"mine": {"source": "countries", "factors": {"chile": "0.9"}}})
        self.assertEqual(factors["mine"]["value"], "20248.9")
        self.assertEqual(factors["mine_change"]["value"], "-484.1")


class NonAdditivity(unittest.TestCase):
    def test_epsilon_range_and_the_top_level_miss(self):
        values = {(scenario, year): cc.baseline(VALUES, scenario, year)
                  for scenario in cc.SCENARIOS for year in cc.YEARS}
        epsilons = {key: Decimal(base["epsilon"]["value"]) for key, base in values.items()}
        self.assertEqual(min(epsilons.values()), Decimal("-139.083"))
        self.assertEqual(min(epsilons, key=epsilons.get), ("hd", "2030"))
        self.assertEqual(max(epsilons.values()), Decimal("53.9176"))
        self.assertEqual(max(epsilons, key=epsilons.get), ("hd", "2040"))
        deltas = {key: base["delta"]["value"] for key, base in values.items() if base["delta"]["value"] != "0"}
        self.assertEqual(deltas, {("cps", "2040"): "1"})
        self.assertEqual(cc.base_year(VALUES)["epsilon"]["value"], "-41.80585")

    def test_a_change_is_applied_to_the_printed_total(self):
        """E4: D' moves only by the change in the component, so the published non-additivity stays in D'."""
        result = cc.assess(VALUES, "hd", "2030", {"ev": {"source": "value", "kt": "2017"}})
        self.assertEqual(result["demand"]["value"], "31967")  # The printed total, not the sum of the parts.
        parts = sum(VALUES[cc.demand_id(line, "hd", "2030")] for line in cc.COMPONENTS)
        self.assertNotEqual(parts + VALUES[cc.demand_id("other-uses", "hd", "2030")], Decimal("31967"))


class Structure(unittest.TestCase):
    def all_replies(self):
        for scenario in cc.SCENARIOS:
            for year in cc.YEARS:
                yield cc.baseline(VALUES, scenario, year)
        yield cc.base_year(VALUES)
        yield cc.assess(VALUES, "steps", "2035", SET_A)

    def test_no_output_combines_mine_and_refining_or_uses_the_2025_dc_cell(self):
        for reply in self.all_replies():
            for item in computed_items(reply):
                uses = item["uses"]
                self.assertFalse(any(u.startswith("iea-refining") for u in uses), item)
                self.assertNotIn(cc.dc_id(None, cc.BASE_YEAR), uses)

    def test_iea_equations_use_iea_figures_only(self):
        for reply in self.all_replies():
            for key in ("coverage", "base", "decomposition"):
                for item in computed_items(reply.get(key, {})):
                    self.assertTrue(all(u.startswith("iea-") for u in item["uses"]), item)

    def test_no_shortage_vocabulary_in_any_field_or_label(self):
        affirmative = re.compile(r"\b(surplus|deficit|shortage|gap|weeks?)\b", re.I)
        for reply in self.all_replies():
            self.assertIsNone(affirmative.search(json.dumps(reply)))
        self.assertIsNone(affirmative.search(json.dumps(cc.DEFINITIONS)))

    def test_the_catalogue_holds_exactly_the_engine_figures(self):
        catalog, _ = copper_inputs.load_catalog(COMMITTED)
        self.assertEqual({item["id"] for item in catalog["figures"]}, cc.figure_ids() | cp.figure_ids())
        self.assertEqual({item["id"] for item in catalog["passages"]}, set(cc.NOTE_IDS) | cp.passage_ids())
        self.assertFalse(cc.figure_ids() & cp.figure_ids())


class Withholding(unittest.TestCase):
    def test_an_unverified_figure_withholds_everything_that_uses_it(self):
        values = {key: value for key, value in VALUES.items() if key != cc.demand_id("total", "steps", "2035")}
        base = cc.baseline(values, "steps", "2035")
        self.assertIsNone(base["coverage"]["residual"]["value"])
        self.assertIsNone(base["coverage"]["share_pct"]["shown"])
        self.assertEqual(base["coverage"]["residual"]["withheld"], [cc.demand_id("total", "steps", "2035")])
        self.assertIsNone(base["decomposition"]["residual_change"]["value"])
        self.assertIsNone(base["delta"]["value"])
        self.assertEqual(base["epsilon"]["value"], "-2.0132")  # Epsilon does not use the total.
        self.assertEqual(base["base"]["residual"]["value"], "4548")
        result = cc.assess(values, "steps", "2035", SET_A)
        self.assertIsNone(result["residual"]["value"])
        self.assertIn(cc.demand_id("total", "steps", "2035"), result["residual"]["withheld"])

    def test_an_unverified_reference_withholds_the_tagged_change(self):
        values = {key: value for key, value in VALUES.items() if key != "fcx-ptfi-sales-guidance-2026"}
        result = cc.assess(values, "steps", "2035", SET_A)
        self.assertIsNone(result["residual"]["value"])
        self.assertIn("fcx-ptfi-sales-guidance-2026", result["residual"]["withheld"])

    def test_a_withheld_country_factor_keeps_its_mine_change_item(self):
        """The mine change is reported whenever a mine control is set, withheld with everything else."""
        values = {key: value for key, value in VALUES.items() if key != cc.mine_id("chile", "2035")}
        result = cc.assess(values, "steps", "2035", {"mine": {"source": "countries", "factors": {"chile": "0.9"}}})
        self.assertIsNotNone(result["mine_change"])
        self.assertIsNone(result["mine_change"]["value"])
        self.assertIn(cc.mine_id("chile", "2035"), result["mine_change"]["withheld"])
        self.assertIsNone(cc.assess(values, "steps", "2035", {})["mine_change"])

    def test_no_values_withholds_everything(self):
        base = cc.baseline({}, "steps", "2035")
        self.assertEqual([item["value"] for item in computed_items(base) if item["value"] is not None], [])


class Refusals(unittest.TestCase):
    def refused(self, assumptions, fragment, scenario="steps", year="2035"):
        with self.assertRaises(ThesisRefused) as raised:
            cc.assess(VALUES, scenario, year, assumptions)
        self.assertEqual(raised.exception.status, 422)
        self.assertIn(fragment, str(raised.exception))

    def test_recycling_in_any_field_is_refused(self):
        for assumptions in ({"recycling": {"kt": "160"}}, {"scrap": "0.3"}, {"Recycled_share": "30"},
                            {"mine": {"source": "total", "kt": "1", "secondary": "5"}}):
            self.refused(assumptions, cc.RECYCLING_REFUSED)

    def test_the_recycling_guard_is_what_refuses_it(self):
        """Mutation: without the recycling guard the request would be refused for a generic reason, not this one."""
        with mock.patch.object(cc, "RECYCLING", re.compile(r"(?!x)x")):
            with self.assertRaises(ThesisRefused) as raised:
                cc.assess(VALUES, "steps", "2035", {"recycling": {"kt": "160"}})
            self.assertNotIn(cc.RECYCLING_REFUSED, str(raised.exception))

    def test_control_refusals(self):
        self.refused({"ev": {"source": "value", "kt": "-1"}}, "cannot be negative")
        self.refused({"ev": {"source": "value", "kt": "2,146"}}, "plain decimal")
        self.refused({"ev": {"source": "value", "kt": 2146}}, "plain decimal")
        self.refused({"ev": {"source": "value", "kt": "1." + "1" * 11}}, "decimal places")
        self.refused({"ev": {"source": "technology_case", "scenario": "steps"}}, "electricity networks")
        self.refused({"networks": {"source": "technology_case", "scenario": "cps"}}, "electricity networks")
        self.refused({"networks": {"source": "scenario", "scenario": "nz"}}, "by its scenario only")
        self.refused({"ev": {"source": "scenario", "scenario": "cps", "kt": "1"}}, "by its scenario only")
        self.refused({"mine": {"source": "countries", "factors": {"chile": "-0.1"}}}, "cannot be negative")
        self.refused({"mine": {"source": "countries", "factors": {"mars": "1"}}}, "unknown fields")
        self.refused({"mine": {"source": "countries", "factors": {}}}, "at least one country")
        self.refused({"mine": {"source": "total", "kt": "-30000"}}, "would be negative")
        self.refused({"mine": {"source": "total", "kt": "1", "reference": "elsewhere"}}, "reference must be")
        self.refused({"solar": {"source": "value", "kt": "1"}}, "unknown fields")
        self.refused([], "must be an object")
        self.refused({}, "scenario must be", scenario="nz")
        self.refused({}, "year must be", year="2025")

    def test_the_negative_guard_is_what_refuses_it(self):
        """Mutation: with negatives allowed, a negative EV value would be computed."""
        original = cc._number

        def signed(value, where, signed=False):
            return original(value, where, signed=True)
        with mock.patch.object(cc, "_number", signed):
            result = cc.assess(VALUES, "steps", "2035", {"ev": {"source": "value", "kt": "-1"}})
        self.assertIsNotNone(result["demand"]["value"])

    def test_outside_published_spread(self):
        result = cc.assess(VALUES, "steps", "2035", {"ev": {"source": "value", "kt": "5000"}})
        self.assertEqual([flag["id"] for flag in result["flags"]], ["user_value", "outside_published_spread"])
        inside = cc.assess(VALUES, "steps", "2035", {"ev": {"source": "value", "kt": "3000"}})
        self.assertEqual([flag["id"] for flag in inside["flags"]], ["user_value"])
        self.assertEqual(inside["demand"]["value"], "33961")


class Display(unittest.TestCase):
    def test_shown_values(self):
        self.assertEqual(cc.shown_kt(Decimal("12789")), ("12,789", False))
        self.assertEqual(cc.shown_kt(Decimal("0.00735")), ("0.00735", False))
        self.assertEqual(cc.shown_kt(Decimal("294.83504050")), ("294.835", True))
        self.assertEqual(cc.shown_kt(Decimal("-41.805850")), ("-41.80585", False))
        self.assertEqual(cc.plain(Decimal("-0")), "0")
        self.assertEqual(cc.plain(Decimal("1.2E+4")), "12000")

    def test_definitions_are_canonical(self):
        text = json.dumps(cc.DEFINITIONS, sort_keys=True)
        self.assertIn("copper-coverage-0.1", text)
        self.assertNotIn("E7", cc.DEFINITIONS["equations"])  # Recycling is not in this version.


if __name__ == "__main__":
    unittest.main()

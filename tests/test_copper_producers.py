"""The published producer unit-cost comparison and the capital-recovery panel (copper_producers) on SYNTHETIC copies of
the filed values: rows reconcile exactly or are withheld, margins only where revenue per pound is retained, capital
per annual tonne, and the panel's exact charges, its zero-rate limit and its refusals."""
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import copper_fakes
from second_order import copper_inputs, copper_linked, copper_producers as cp
from second_order.thesis_rules import ThesisRefused


def synthetic_values() -> dict[str, Decimal]:
    with tempfile.TemporaryDirectory() as temp:
        root = copper_fakes.write_sources(Path(temp))
        catalog = copper_inputs.check_catalog(copper_fakes.catalog(root))
        _, states = copper_inputs.check_items(catalog, root)
        return copper_inputs.verified_values(catalog, states)


VALUES = synthetic_values()
# The current Bagdad statement's two computed inputs, as copper_linked.linked_values gives them when verified.
LINKED = {"nr-bagdad-capex-estimate": Decimal("4.5"), "nr-bagdad-cu-increment": Decimal("225")}
BOTH = VALUES | LINKED
CURRENT = "bagdad-2026-11-04"


class CostRows(unittest.TestCase):
    def test_every_row_reconciles_exactly(self):
        rows = {row["id"]: row for row in cp.cost_rows(VALUES)}
        self.assertEqual({key: (row["state"], row["reconciles"]) for key, row in rows.items()},
                         {"fcx-us": ("available", True), "fcx-south-america": ("available", True),
                          "fcx-indonesia": ("available", True), "fcx-consolidated": ("available", None),
                          "scco": ("available", True)})
        for row in cp.ROWS:
            if row["credits"] or row["other"]:
                parts = [VALUES[figure] for figure in [row["before"], *row["credits"], *row["other"]]]
                self.assertEqual(sum(parts), VALUES[row["net"]])
        self.assertEqual(VALUES["fcx-id-unit-net-2025"], Decimal("-0.55"))  # A net credit, as the filing prints it.

    def test_a_row_that_does_not_reconcile_is_withheld(self):
        values = {**VALUES, "fcx-us-treatment-2025": Decimal("0.14")}
        rows = {row["id"]: row for row in cp.cost_rows(values)}
        self.assertEqual((rows["fcx-us"]["state"], rows["fcx-us"]["reconciles"]), ("withheld", False))
        self.assertIn("do not reconcile", rows["fcx-us"]["problem"])
        self.assertNotIn("0.14", json.dumps(rows["fcx-us"]))
        margins = {margin["row"]: margin for margin in cp.margins(values, list(rows.values()))}
        self.assertEqual((margins["fcx-us"]["state"], margins["fcx-us"]["shown"]), ("withheld", None))

    def test_the_reconciliation_is_what_withholds_it(self):
        """Mutation: a reconciliation that always passes would show the non-reconciling row."""
        values = {**VALUES, "fcx-us-treatment-2025": Decimal("0.14")}
        always = type("Always", (), {"__eq__": lambda self, other: True})()
        with mock.patch("builtins.sum", lambda parts, start=0: always):
            rows = {row["id"]: row for row in cp.cost_rows(values)}
        self.assertEqual(rows["fcx-us"]["state"], "available")

    def test_an_unverified_figure_withholds_its_row(self):
        values = {key: value for key, value in VALUES.items() if key != "scco-by-products-2025"}
        rows = {row["id"]: row for row in cp.cost_rows(values)}
        self.assertEqual((rows["scco"]["state"], rows["scco"]["withheld"]), ("withheld", ["scco-by-products-2025"]))
        self.assertEqual(rows["fcx-us"]["state"], "available")


class Margins(unittest.TestCase):
    def test_margins_only_where_revenue_per_pound_is_retained(self):
        margins = {margin["row"]: margin for margin in cp.margins(VALUES, cp.cost_rows(VALUES))}
        self.assertEqual({key: margin["shown"] for key, margin in margins.items()},
                         {"fcx-us": "1.86", "fcx-south-america": "2.36", "fcx-indonesia": "5.08", "scco": None})
        self.assertEqual(margins["scco"]["state"], "not_retained")
        self.assertIn("not among the retained figures", margins["scco"]["problem"])
        self.assertEqual(margins["fcx-us"]["gross_profit"], "fcx-us-gross-profit-2025")

    def test_the_wording_claims_nothing_about_closure(self):
        """The texts may name the question only to deny it; no affirmative claim about closure or investment."""
        text = " ".join([cp.CAN_ESTABLISH, *cp.CANNOT_ESTABLISH, cp.BROWNFIELD_GREENFIELD, cp.SCCO_MARGIN]).lower()
        for affirmative in ("not at risk of clos", "is at risk of clos", "will close", "will be built",
                            "safe from closure", "marginal mine is", "incentive price is"):
            self.assertNotIn(affirmative, text)
        self.assertIn("avoidable cost", text)
        self.assertNotRegex(" ".join(row["fcx"] + row["scco"] for row in cp.MATRIX), r"\d")


class Projects(unittest.TestCase):
    def test_capital_per_annual_tonne(self):
        projects = {project["id"]: project for project in cp.projects(BOTH)}
        self.assertEqual({key: [item["shown"] for item in project["capital_per_annual_tonne"]]
                          for key, project in projects.items()},
                         {CURRENT: ["44,092"], "bagdad": ["38,581", "30,865"], "el-abra": [], "tia-maria": ["15,042"],
                          "los-chancas": ["20,000"], "michiquillay": ["11,111"]})
        self.assertIn("states no capital", projects["el-abra"]["intensity_problem"])
        self.assertEqual(projects["bagdad"]["type"], "brownfield")
        self.assertEqual({projects[key]["type"] for key in ("tia-maria", "los-chancas", "michiquillay")},
                         {"greenfield"})

    def test_the_current_row_is_first_and_the_earlier_second(self):
        self.assertEqual([project["id"] for project in cp.projects(BOTH)][:2], [CURRENT, "bagdad"])
        statements = {project["id"]: project["statement"] for project in cp.projects(BOTH)}
        self.assertEqual(statements[CURRENT], {"kind": "company_estimates", "source_of": "nr-bagdad-capex-estimate"})
        self.assertEqual(statements["bagdad"], {"kind": "earlier_statement", "source_of": "fcx-bagdad-capital-2025"})
        self.assertEqual({key for key, value in statements.items() if value is None},
                         {"el-abra", "tia-maria", "los-chancas", "michiquillay"})

    def test_without_linked_values_only_the_current_row_is_withheld(self):
        projects = {project["id"]: project for project in cp.projects(VALUES)}
        current = projects[CURRENT]["capital_per_annual_tonne"]
        self.assertEqual([(item["shown"], item["withheld"]) for item in current],
                         [(None, ["nr-bagdad-capex-estimate", "nr-bagdad-cu-increment"])])
        self.assertEqual([item["shown"] for item in projects["bagdad"]["capital_per_annual_tonne"]], ["38,581", "30,865"])

    def test_break_even_is_never_an_incentive(self):
        projects = {project["id"]: project for project in cp.projects(BOTH)}
        self.assertEqual((projects[CURRENT]["incentive"], projects[CURRENT]["break_even"],
                          projects[CURRENT]["break_even_condition"]),
                         ([], ["nr-bagdad-breakeven-cu"], "nr-bagdad-breakeven-mo"))
        self.assertFalse(any(set(project["incentive"]) & set(copper_linked.FIGURES) for project in projects.values()))
        self.assertEqual({key for key, project in projects.items() if project["break_even"]}, {CURRENT})
        self.assertEqual(projects[CURRENT]["capacity_label"], cp.CAPACITY_LABEL)
        self.assertEqual(projects[CURRENT]["caveats"], ["nr-p-cost-risk", "nr-p-estimates-change"])
        self.assertEqual(projects[CURRENT]["passages"], ["nr-p-board-approval", "q3-p-bagdad-approval", "nr-p-schedule"])
        self.assertEqual(projects[CURRENT]["construction"], "nr-bagdad-construction-years")

    def test_the_catalogue_ids_are_unchanged(self):
        ids = cp.figure_ids() | cp.passage_ids()
        self.assertFalse([item for item in ids if item.startswith(("nr-", "q3-"))])
        self.assertFalse(ids & (set(copper_linked.FIGURES) | set(copper_linked.PASSAGES)))

    def test_the_notes(self):
        self.assertEqual(cp.comparison(BOTH)["notes"], {
            "incentive_break_even": "The company used 'incentive copper price' in its 10-Ks and 'break-even economics' "
                                    "in the approval release. Neither term is defined in these documents; this project "
                                    "does not treat them as the same figure or derive one from the other.",
            "no_path": "The company gives a first production target and a long-term annual rate, but no year-by-year "
                       "path; nothing between them is shown or assumed."})
        self.assertEqual(cp.comparison(BOTH)["version"], "copper-producers-0.2")

    def test_exact_pound_conversion(self):
        self.assertEqual(cp.LB_PER_TONNE, Fraction(1000) / Fraction("0.45359237"))
        self.assertEqual(cp.half_even(cp.LB_PER_TONNE, 8), "2,204.62262185")


class CapitalPanel(unittest.TestCase):
    def charges(self, rate, years):
        reply = cp.capital_charge(VALUES, rate, years)
        return reply, {row["project"]: [charge["shown"] for charge in row["charges"]] for row in reply["projects"]}

    def test_the_design_table(self):
        table = {("6", "15"): ("0.702", ["1.802", "1.441"]), ("6", "20"): ("0.595", ["1.526", "1.221"]),
                 ("6", "25"): ("0.534", ["1.369", "1.095"]), ("8", "15"): ("0.797", ["2.045", "1.636"]),
                 ("8", "20"): ("0.695", ["1.782", "1.426"]), ("8", "25"): ("0.639", ["1.639", "1.312"]),
                 ("10", "15"): ("0.897", ["2.301", "1.841"]), ("10", "20"): ("0.801", ["2.056", "1.644"]),
                 ("10", "25"): ("0.752", ["1.928", "1.542"])}
        for (rate, years), (tia, bagdad) in table.items():
            reply, charges = self.charges(rate, years)
            self.assertEqual((charges["tia-maria"], charges["bagdad"]), ([tia], bagdad), (rate, years))
            self.assertEqual(reply["method"], "annuity")
        reply, _ = self.charges("8", "20")
        self.assertEqual(reply["crf"], "0.101852")

    def test_the_current_row_charges(self):
        for (rate, years), shown in ((("8", "20"), ["2.037"]), (("0", "20"), ["1.000"]), (("6", "25"), ["1.565"])):
            reply = cp.capital_charge(BOTH, rate, years)
            row = next(item for item in reply["projects"] if item["project"] == CURRENT)
            self.assertEqual([charge["shown"] for charge in row["charges"]], shown, (rate, years))
            self.assertEqual(row["charges"][0]["uses"], ["nr-bagdad-capex-estimate", "nr-bagdad-cu-increment"])
        withheld = next(item for item in cp.capital_charge(VALUES, "8", "20")["projects"] if item["project"] == CURRENT)
        self.assertEqual([charge["shown"] for charge in withheld["charges"]], [None])

    def test_a_zero_rate_recovers_the_capital_evenly(self):
        reply, charges = self.charges("0", "20")
        self.assertEqual((reply["method"], reply["crf"]), ("limit_at_zero_rate", "0.050000"))
        self.assertEqual(charges["tia-maria"], ["0.341"])  # $1,805m / 20 = $90.25m a year, per pound of capacity.
        self.assertEqual(charges["bagdad"], ["0.875", "0.700"])
        for years, tia, bagdad in (("15", "0.455", ["1.167", "0.933"]), ("25", "0.273", ["0.700", "0.560"])):
            _, charges = self.charges("0", years)
            self.assertEqual((charges["tia-maria"], charges["bagdad"]), ([tia], bagdad))
        self.assertEqual(self.charges("0.0", "20")[1]["tia-maria"], ["0.341"])

    def test_the_general_formula_approaches_one_over_n(self):
        for years in (1, 15, 20, 100):
            limit = cp.crf(Fraction(0), years)
            self.assertEqual(limit, Fraction(1, years))
            near = cp.crf(Fraction(1, 10 ** 12), years)
            self.assertLess(abs(near - limit), Fraction(1, 10 ** 9))
            self.assertGreater(near, limit)  # A positive rate always charges more than recovering the capital alone.

    def test_the_zero_rate_branch_is_needed(self):
        """Mutation: the general formula alone divides zero by zero at r = 0."""
        with self.assertRaises(ZeroDivisionError):
            rate, growth = Fraction(0), Fraction(1) ** 20
            rate * growth / (growth - 1)

    def test_one_year(self):
        reply, charges = self.charges("8", "1")
        self.assertEqual(reply["crf"], "1.080000")
        self.assertEqual(charges["tia-maria"], [cp.half_even(Fraction(1805 * 10 ** 6) * Fraction(108, 100)
                                                             / (120000 * cp.LB_PER_TONNE), 3)])

    def test_refusals(self):
        for rate, years in (("-1", "20"), ("abc", "20"), ("101", "20"), ("8.12345", "20"), ("1e1", "20"), (8, "20"),
                            ("8", "0"), ("8", "-1"), ("8", "2.5"), ("8", "101"), ("8", 20), ("8", "")):
            with self.assertRaises(ThesisRefused) as raised:
                cp.capital_charge(VALUES, rate, years)
            self.assertEqual(raised.exception.status, 422, (rate, years))

    def test_the_panel_names_no_price_and_solves_for_none(self):
        reply, _ = self.charges("8", "20")
        self.assertIsNone(re.search(r"incentive|breakeven|break-even|required price|price", json.dumps(reply), re.I))
        names = [name for name in dir(cp) if callable(getattr(cp, name))]
        self.assertEqual([name for name in names if re.search(r"solve|breakeven|incentive|price", name, re.I)], [])
        self.assertEqual(reply["stored"], False)
        self.assertEqual(reply["ignores"], list(cp.IGNORES))

    def test_the_name_scan_catches_a_solver(self):
        """Mutation: a function that solved for a price would be caught by the scan above."""
        with mock.patch.object(cp, "solve_price", lambda: None, create=True):
            names = [name for name in dir(cp) if callable(getattr(cp, name))]
            self.assertIn("solve_price", [name for name in names if re.search(r"solve|price", name, re.I)])

    def test_an_unverified_capital_withholds_its_charge(self):
        values = {key: value for key, value in VALUES.items() if key != "scco-tia-maria-budget-2025"}
        reply = cp.capital_charge(values, "8", "20")
        tia = next(row for row in reply["projects"] if row["project"] == "tia-maria")
        self.assertEqual((tia["charges"][0]["shown"], tia["charges"][0]["withheld"]),
                         (None, ["scco-tia-maria-budget-2025"]))


class HalfEven(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(cp.half_even(Fraction(5, 2), 0), "2")
        self.assertEqual(cp.half_even(Fraction(7, 2), 0), "4")
        self.assertEqual(cp.half_even(Fraction(-5, 2), 0), "-2")
        self.assertEqual(cp.half_even(Fraction(-1, 3), 2), "-0.33")
        self.assertEqual(cp.half_even(Fraction(-1, 1000), 2), "0.00")
        self.assertEqual(cp.half_even(Fraction(1234567, 1000), 2), "1,234.57")


if __name__ == "__main__":
    unittest.main()

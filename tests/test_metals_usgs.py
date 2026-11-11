import unittest

import metals_fakes
from second_order import metals_usgs
from second_order.metals_usgs import UsgsRefused, number, read


def chapter(chapters, chapter_name):
    return next(item for item in chapters if item["chapter"] == chapter_name)


def only_series(chapters, chapter_name, statistic):
    return next(item for item in chapter(chapters, chapter_name)["series"] if item["statistic"] == statistic)


class UsgsReaderTests(unittest.TestCase):
    def setUp(self):
        self.chapters = read(metals_fakes.usgs_rows())

    def test_chapters_in_spec_order_with_frame(self):
        self.assertEqual(len(self.chapters), 45)
        self.assertEqual(self.chapters[0]["id"], "aluminum")
        self.assertEqual([item["chapter"] for item in self.chapters], metals_usgs.CHAPTER_NAMES)
        ids = [item["id"] for item in self.chapters]
        self.assertIn("rare-earths-heavy", ids)
        self.assertIn("niobium-columbium", ids)
        self.assertEqual(metals_usgs.chapter_id("BAUXITE AND ALUMINA"), "bauxite-and-alumina")
        self.assertEqual(metals_usgs.display_name("PLATINUM-GROUP METALS"), "Platinum-group metals")
        absent = chapter(self.chapters, "ZINC")
        self.assertFalse(absent["present"])
        self.assertEqual(absent["series"], [])
        self.assertFalse(absent["world_table"])
        cobalt = chapter(self.chapters, "COBALT")
        self.assertTrue(cobalt["present"] and cobalt["world_table"])
        self.assertEqual(cobalt["critical"], "Yes")
        self.assertEqual(chapter(self.chapters, "COPPER")["critical"], "No")

    def test_share_of_stated_world_total(self):
        mine = only_series(self.chapters, "COBALT", "Production")
        congo = next(cell for cell in mine["countries"] if cell["country"] == "Congo (Kinshasa)")
        self.assertEqual(congo["value"], "230,000")
        self.assertEqual(congo["share"]["shown"], "74.2")
        self.assertEqual(mine["world"]["number"], "310000")
        self.assertEqual(mine["other"]["share"]["shown"], "2.9")
        self.assertEqual(mine["leader"]["countries"], ["Congo (Kinshasa)"])
        self.assertEqual(mine["top3"]["countries"], ["Congo (Kinshasa)", "Indonesia", "United States"])
        self.assertEqual(mine["top3"]["shown"], "88.5")
        self.assertIsNone(mine["no_shares"])

    def test_rounded_world_detail_joins_its_series(self):
        cobalt = chapter(self.chapters, "COBALT")
        mine = cobalt["series"][0]
        self.assertEqual(mine["detail"], "Mine production")
        self.assertEqual(len(mine["countries"]), 3)
        self.assertEqual(mine["id"], "cobalt/production/mine-production/metric-tons/2025")
        titanium = chapter(self.chapters, "TITANIUM AND TITANIUM DIOXIDE")["series"]
        self.assertEqual(len(titanium), 2)
        ilmenite, both = titanium
        self.assertEqual(ilmenite["detail"], "Mine production: Ilmenite")
        self.assertEqual([cell["country"] for cell in ilmenite["countries"]], ["Australia", "China"])
        self.assertEqual(ilmenite["world"]["number"], "6000")
        self.assertEqual(both["detail"], "Mine production: ilmenite and rutile")
        self.assertEqual(both["countries"], [])
        self.assertEqual(both["no_shares"], "USGS prints no country for this series")
        self.assertEqual(both["world"]["number"], "7000")

    def test_qualified_world_total_withholds_all_shares(self):
        mine = only_series(self.chapters, "RARE EARTHS", "Production")
        reason = "The world total is printed as “>2,000,000”, not as a number"
        self.assertEqual(mine["no_shares"], reason)
        for cell in mine["countries"]:
            self.assertEqual(cell["share"], {"shown": None, "reason": reason})
        self.assertEqual(mine["top3"]["shown"], None)
        self.assertEqual(mine["top3"]["reason"], reason)
        self.assertEqual(mine["leader"]["reason"], reason)

    def test_missing_and_repeated_world_totals_withhold_shares(self):
        gallium = only_series(self.chapters, "GALLIUM", "Production")
        self.assertEqual(gallium["no_shares"], "USGS prints more than one world total for this series")
        rows = [row for row in metals_fakes.usgs_rows() if not (row[0] == "GOLD" and row[3] == "World total")]
        gold = only_series(read(rows), "GOLD", "Production")
        self.assertEqual(gold["no_shares"], "USGS prints no world total for this series")
        self.assertIsNone(gold["world"])
        self.assertEqual(gold["countries"][0]["share"]["reason"], "USGS prints no world total for this series")

    def test_withheld_country_blocks_order(self):
        mine = only_series(self.chapters, "NICKEL", "Production")
        withheld = next(cell for cell in mine["countries"] if cell["country"] == "United States")
        self.assertEqual(withheld["share"], {"shown": None, "reason": "Printed as “W”"})
        reason = "United States is printed as “W”, so the order is unknown"
        for part in (mine["leader"], mine["top3"]):
            self.assertIsNone(part["shown"])
            self.assertEqual(part["reason"], reason)
        indonesia = next(cell for cell in mine["countries"] if cell["country"] == "Indonesia")
        self.assertEqual(indonesia["share"]["shown"], "59.5")

    def test_fewer_than_three_countries_withholds_only_the_top_three(self):
        gold = only_series(self.chapters, "GOLD", "Production")
        self.assertEqual(gold["leader"]["countries"], ["China"])
        self.assertEqual(gold["leader"]["shown"], "12.7")
        self.assertIsNone(gold["top3"]["shown"])
        self.assertEqual(gold["top3"]["reason"], "Fewer than three countries are named")

    def test_tie_at_third_is_by_name(self):
        first = only_series(self.chapters, "LEAD", "Production")
        swapped = only_series(read(metals_fakes.usgs_rows(swap_tie=True)), "LEAD", "Production")
        self.assertEqual(first["top3"]["countries"], ["Big", "Mid", "Alpha"])
        self.assertEqual(first["top3"]["shown"], "75.0")
        self.assertEqual(swapped["top3"], first["top3"])

    def test_dash_counts_as_zero_in_the_order(self):
        tin = only_series(self.chapters, "TIN", "Production")
        dash = next(cell for cell in tin["countries"] if cell["country"] == "Delta")
        self.assertEqual((dash["value"], dash["number"]), ("—", None))
        self.assertEqual(dash["share"], {"shown": None, "reason": "Printed as “—”"})
        self.assertEqual(tin["leader"], {"countries": ["Kappa"], "shown": "40.0", "reason": None})
        self.assertEqual(tin["top3"], {"countries": ["Kappa", "Omega", "Sigma"], "shown": "90.0", "reason": None})
        tm = "metric tons"
        rows = metals_fakes.usgs_rows()
        rows += metals_fakes._table("ZINC", "Zinc", "Production", "Mine production", "Mine production: rounded", tm,
                                    "2025", [("Zulu", " — "), ("Bravo", "—"), ("Mike", "8")], "10")
        zinc = only_series(read(rows), "ZINC", "Production")
        self.assertEqual(zinc["top3"], {"countries": ["Mike", "Bravo", "Zulu"], "shown": "80.0", "reason": None})
        self.assertEqual(zinc["leader"]["countries"], ["Mike"])
        rows = metals_fakes.usgs_rows()
        rows += metals_fakes._table("ZINC", "Zinc", "Production", "Mine production", "Mine production: rounded", tm,
                                    "2025", [("Bravo", "—"), ("Mike", "8"), ("Zulu", "NA"), ("Kilo", "1")], "10")
        blocked = only_series(read(rows), "ZINC", "Production")
        for part in (blocked["leader"], blocked["top3"]):
            self.assertEqual(part, {"countries": [], "shown": None,
                                    "reason": "Zulu is printed as “NA”, so the order is unknown"})

    def test_world_total_printed_as_zero_has_its_own_reason(self):
        rows = metals_fakes.usgs_rows()
        rows += metals_fakes._table("ZINC", "Zinc", "Production", "Mine production", "Mine production: rounded",
                                    "metric tons", "2025", [("Mike", "0")], "0")
        zinc = only_series(read(rows), "ZINC", "Production")
        reason = "The world total is printed as “0”, so no share can be computed"
        self.assertEqual(zinc["no_shares"], reason)
        self.assertEqual(zinc["countries"][0]["share"], {"shown": None, "reason": reason})
        self.assertEqual(zinc["leader"]["reason"], reason)

    def test_world_total_says_whether_usgs_rounded_it(self):
        self.assertIs(only_series(self.chapters, "COBALT", "Production")["world"]["rounded"], True)
        self.assertIs(only_series(self.chapters, "BAUXITE AND ALUMINA", "Production")["world"]["rounded"], True)
        self.assertIs(only_series(self.chapters, "TIN", "Production")["world"]["rounded"], False)
        cobalt = only_series(self.chapters, "COBALT", "Production")
        self.assertNotIn("rounded", cobalt["other"])
        self.assertNotIn("rounded", cobalt["countries"][0])

    def test_years_of_reserves_pairs_only_same_basis(self):
        copper = chapter(self.chapters, "COPPER")["years_of_reserves"]
        self.assertEqual(len(copper), 1)
        self.assertEqual(copper[0]["shown"], "43")
        self.assertIsNone(copper[0]["reason"])
        self.assertEqual(copper[0]["label"], metals_usgs.YEARS_LABEL)
        self.assertEqual(copper[0]["reserves"], "copper/reserves/reserves/metric-tons/2025")
        self.assertEqual(copper[0]["production"], "copper/production/mine-production/metric-tons/2025")
        bauxite = chapter(self.chapters, "BAUXITE AND ALUMINA")["years_of_reserves"]
        self.assertEqual([entry["shown"] for entry in bauxite], ["64"])
        self.assertEqual(chapter(self.chapters, "IRON ORE")["years_of_reserves"], [])

    def test_years_of_reserves_states_why_it_is_withheld(self):
        rows = [list(row) for row in metals_fakes.usgs_rows()]
        for row in rows:
            if row[0] == "COPPER" and row[3] == "World total" and row[4] == "Production":
                row[8] = "W"
        entry = chapter(read(rows), "COPPER")["years_of_reserves"][0]
        self.assertIsNone(entry["shown"])
        self.assertEqual(entry["reason"], "Production: The world total is printed as “W”, not as a number")

    def test_a_valid_ratio_under_one_year_is_shown_as_less_than_one(self):
        # Compatible units and no known issue: the size of the result alone never withholds it.
        silver = chapter(self.chapters, "SILVER")
        self.assertEqual([item["unit_issue"] for item in silver["series"]], [None, None])
        (entry,) = silver["years_of_reserves"]
        self.assertEqual((entry["shown"], entry["reason"]), ("less than 1", None))
        self.assertEqual(entry["shown"], metals_usgs.YEARS_UNDER_ONE)

        def silver_years(reserves):
            rows = [list(row) for row in metals_fakes.usgs_rows()]
            for row in rows:
                if row[0] == "SILVER" and row[3] == "World total" and row[4] == "Reserves":
                    row[8] = reserves
            return chapter(read(rows), "SILVER")["years_of_reserves"][0]["shown"]
        # 999/1000 would round half-even to "1"; under one year it still reads "less than 1". At exactly one, "1".
        self.assertEqual(silver_years("999"), "less than 1")
        self.assertEqual(silver_years("1,000"), "1")
        self.assertEqual(silver_years("1,499"), "1")

    def test_a_known_unit_issue_withholds_the_quantities_basis_and_the_years(self):
        vanadium = chapter(self.chapters, "VANADIUM")
        sid = "vanadium/reserves/reserves/metric-tons/2025"
        issue = metals_usgs.UNIT_ISSUES[sid]
        self.assertIn("thousand metric tons", issue)
        self.assertIn("page 2", issue)
        reserves = next(item for item in vanadium["series"] if item["id"] == sid)
        production = next(item for item in vanadium["series"] if item["statistic"] == "Production")
        self.assertEqual((reserves["unit_issue"], production["unit_issue"]), (issue, None))
        # A share is a part over a total of the same column, so a scale in doubt leaves the shares and the order.
        theta = next(cell for cell in reserves["countries"] if cell["country"] == "Theta")
        self.assertEqual(theta["share"], {"shown": "50.0", "reason": None})
        self.assertEqual(reserves["leader"]["countries"], ["Theta"])
        (entry,) = vanadium["years_of_reserves"]
        self.assertEqual((entry["shown"], entry["reason"]), (None, "Reserves: " + issue))
        flagged = [item["id"] for chapter_ in self.chapters for item in chapter_["series"] if item["unit_issue"]]
        self.assertEqual(flagged, [sid])

    def test_a_unit_issue_names_one_exact_series(self):
        # Printed in another unit, the series has another id: the issue no longer applies, and the pair needs the
        # same unit, so no years figure is made from it.
        rows = [list(row) for row in metals_fakes.usgs_rows()]
        for row in rows:
            if row[0] == "VANADIUM" and row[4] == "Reserves":
                row[6] = "thousand metric tons"
        vanadium = chapter(read(rows), "VANADIUM")
        self.assertEqual([item["unit_issue"] for item in vanadium["series"]], [None, None])
        self.assertEqual(vanadium["years_of_reserves"], [])

    def test_a_world_problem_comes_before_a_unit_issue(self):
        rows = [list(row) for row in metals_fakes.usgs_rows()]
        for row in rows:
            if row[0] == "VANADIUM" and row[3] == "World total" and row[4] == "Reserves":
                row[8] = "W"
        (entry,) = chapter(read(rows), "VANADIUM")["years_of_reserves"]
        self.assertEqual(entry["reason"], "Reserves: The world total is printed as “W”, not as a number")

    def test_years_of_reserves_needs_only_numeric_world_totals(self):
        rows = metals_fakes.usgs_rows()
        tm = "metric tons"
        rows.append(metals_fakes._row("ZINC", "Zinc", "World total", "Production", "Mine production: rounded", tm,
                                      "2025", "12,000"))
        rows.append(metals_fakes._row("ZINC", "Zinc", "World total", "Reserves", "Reserves: rounded", tm, "2025",
                                      "240,000"))
        zinc = chapter(read(rows), "ZINC")
        self.assertEqual([item["no_shares"] for item in zinc["series"]], ["USGS prints no country for this series"] * 2)
        self.assertEqual(len(zinc["years_of_reserves"]), 1)
        self.assertEqual(zinc["years_of_reserves"][0]["shown"], "20")
        self.assertIsNone(zinc["years_of_reserves"][0]["reason"])

    def test_imports_and_reliance_as_printed(self):
        rare = chapter(self.chapters, "RARE EARTHS")
        self.assertEqual([item["detail"] for item in rare["imports"]],
                         ["Rare-earth compounds and metals", "Rare-earth magnets"])
        compounds = rare["imports"][0]
        self.assertEqual(compounds["years"], "2021–24")
        self.assertEqual(compounds["rows"][0], {"country": "China", "value": "70", "number": "70"})
        self.assertEqual([item["value"] for item in rare["reliance"]], ["E", ">95"])
        self.assertEqual([item["year"] for item in rare["reliance"]], ["2024", "2025"])
        self.assertEqual({item["commodity"] for item in rare["reliance"]}, {"Rare earths"})

    def test_reliance_rows_carry_their_commodity(self):
        # One detail, two commodities: only the Commodity column tells the two 2025 figures apart.
        titanium = chapter(self.chapters, "TITANIUM AND TITANIUM DIOXIDE")["reliance"]
        detail = "Net import reliance as a percentage of apparent consumption"
        self.assertEqual(titanium, [
            {"commodity": "Titanium sponge metal", "detail": detail, "year": "2025", "value": "100"},
            {"commodity": "TiO2 pigment", "detail": detail, "year": "2025", "value": "E"}])

    def test_header_and_row_length_must_match(self):
        rows = metals_fakes.usgs_rows()
        rows[0] = ["Chapter"] + rows[0][1:]
        with self.assertRaises(UsgsRefused):
            read(rows)
        short = metals_fakes.usgs_rows()
        short[3] = short[3][:-1]
        with self.assertRaises(UsgsRefused):
            read(short)

    def test_colliding_series_ids_are_refused(self):
        rows = metals_fakes.usgs_rows()
        rows.append(["COBALT", metals_fakes.WORLD_SECTION, "Cobalt", "Peru", "Production", "Mine production!",
                     "metric tons", "2025", "1", "", "Yes", ""])
        with self.assertRaises(UsgsRefused):
            read(rows)

    def test_number_forms(self):
        self.assertEqual(number("1,301"), "1301")
        self.assertEqual(number("0.5"), "0.5")
        self.assertEqual(number(" 12 "), "12")
        for printed in ("W", ">50", "330 - 390", "—", "", "1,30"):
            self.assertIsNone(number(printed), printed)


if __name__ == "__main__":
    unittest.main()

import unittest

import metals_fakes
from second_order import metals_risk, metals_usgs

COBALT_MINE = "cobalt/production/mine-production/metric-tons/2025"
COPPER_MINE = "copper/production/mine-production/metric-tons/2025"
COPPER_REFINERY = "copper/production/refinery-production/metric-tons/2025"


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.rows = metals_fakes.usgs_rows()
        self.result = metals_risk.read(metals_usgs.read(self.rows), self.rows)

    def entry(self, chapter_id):
        return next(item for item in self.result if item["id"] == chapter_id)

    def indicators(self, chapter_id, series_id):
        return self.entry(chapter_id)["series"][series_id]

    def test_one_entry_per_chapter_in_order(self):
        self.assertEqual([item["id"] for item in self.result],
                         [metals_usgs.chapter_id(name) for name in metals_usgs.CHAPTER_NAMES])
        zinc = self.entry("zinc")
        self.assertEqual(zinc["series"], {})
        self.assertEqual(zinc["stages"], [])
        self.assertEqual(zinc["missing_stages"], ["mining", "refining"])
        self.assertIsNone(zinc["leaders_differ"])
        self.assertIsNone(zinc["most_concentrated"])
        self.assertIsNone(zinc["alternatives"])
        self.assertEqual(zinc["us"], {"reliance": None, "imports": [], "secondary": []})

    def test_cobalt_bounds_with_a_remainder(self):
        self.assertEqual(self.indicators("cobalt", COBALT_MINE),
                         {"named_share": "88.5", "over_total": False, "hhi_low": "5706", "hhi_high": "5839",
                          "named": 3, "reason": None})

    def test_tin_dash_counts_as_zero(self):
        got = self.indicators("tin", "tin/production/mine-production/metric-tons/2025")
        self.assertEqual(got, {"named_share": "90.0", "over_total": False, "hhi_low": "2900", "hhi_high": "3000",
                               "named": 3, "reason": None})

    def test_nickel_w_withholds_with_the_order_reason(self):
        got = self.indicators("nickel", "nickel/production/mine-production/metric-tons/2025")
        self.assertEqual(got, {"named_share": None, "over_total": None, "hhi_low": None, "hhi_high": None,
                               "named": None, "reason": "United States is printed as “W”, so the order is unknown"})

    def test_qualified_world_total_withholds(self):
        got = self.indicators("rare-earths", "rare-earths/production/mine-production/metric-tons/2025")
        self.assertIsNone(got["hhi_low"])
        self.assertEqual(got["reason"], "The world total is printed as “>2,000,000”, not as a number")

    def test_named_sum_above_the_world_total(self):
        got = self.indicators("manganese", "manganese/production/mine-production/metric-tons/2025")
        self.assertEqual(got, {"named_share": "110.0", "over_total": True, "hhi_low": "6100", "hhi_high": "6100",
                               "named": 2, "reason": None})

    def test_stages_and_leaders_differ(self):
        copper = self.entry("copper")
        self.assertEqual([(s["series"], s["detail"], s["stage"]) for s in copper["stages"]],
                         [(COPPER_MINE, "Mine production", "mining"),
                          (COPPER_REFINERY, "Refinery production", "refining")])
        self.assertEqual(copper["stages"][0]["leader"]["countries"], ["Chile"])
        self.assertEqual(copper["stages"][1]["leader"]["countries"], ["China"])
        self.assertEqual(copper["stages"][1]["top3"]["reason"], "Fewer than three countries are named")
        self.assertEqual(copper["missing_stages"], [])
        self.assertTrue(copper["leaders_differ"])
        self.assertEqual(copper["most_concentrated"], COPPER_REFINERY)
        self.assertEqual(set(copper["series"]),
                         {COPPER_MINE, COPPER_REFINERY, "copper/reserves/reserves/metric-tons/2025"})
        self.assertEqual(copper["series"][COPPER_REFINERY]["hhi_high"], "4348")

    def test_missing_stages_and_other_stage(self):
        cobalt = self.entry("cobalt")
        self.assertEqual(cobalt["missing_stages"], ["refining"])
        self.assertIsNone(cobalt["leaders_differ"])
        self.assertEqual(cobalt["most_concentrated"], COBALT_MINE)
        gallium = self.entry("gallium")
        self.assertEqual(gallium["stages"][0]["stage"], "other")
        self.assertEqual(gallium["missing_stages"], ["mining", "refining"])
        self.assertIsNone(gallium["most_concentrated"])  # No leader: the world total is printed twice.

    def test_stage_names(self):
        self.assertEqual(metals_risk.stage_of("Bauxite, mine production"), "mining")
        self.assertEqual(metals_risk.stage_of("Smelter production"), "refining")
        self.assertEqual(metals_risk.stage_of("Refined: Primary"), "refining")
        self.assertEqual(metals_risk.stage_of("Primary production"), "other")
        self.assertEqual(metals_risk.stage_of("Determine"), "other")

    def test_an_export_series_is_no_stage(self):
        # Mercury's chapter prints "Mine production: exports": a trade flow, not the mining stage.
        self.assertEqual(metals_risk.stage_of("Mine production: exports"), "other")
        self.assertEqual(metals_risk.stage_of("Smelter production, Exports of refined"), "other")
        self.assertEqual(metals_risk.stage_of("Mine production: Exporting countries' share"), "other")
        self.assertEqual(metals_risk.stage_of("Mine production: expected"), "mining")

    def test_alternatives_on_a_pair(self):
        copper = self.entry("copper")
        self.assertEqual(copper["alternatives"], [])  # Chile's reserves share is below its production share.
        self.assertEqual(copper["reserves_only"], [{"country": "Peru", "reserves": "12.2"}])
        manganese = self.entry("manganese")
        self.assertEqual(manganese["alternatives"], [{"country": "Beta", "reserves": "60.0", "production": "50.0"}])
        self.assertEqual(manganese["reserves_only"], [{"country": "Gamma", "reserves": "5.0"}])
        self.assertIsNone(self.entry("cobalt")["alternatives"])
        self.assertIsNone(self.entry("cobalt")["reserves_only"])

    def test_reliance_is_the_first_2025_row(self):
        detail = "Net import reliance as a percentage of apparent consumption"
        self.assertEqual(self.entry("rare-earths")["us"]["reliance"],
                         {"commodity": "Rare earths", "detail": detail, "value": ">95"})
        self.assertIsNone(self.entry("cobalt")["us"]["reliance"])
        # Two 2025 rows under one detail: the first in file order, named by its commodity.
        self.assertEqual(self.entry("titanium-and-titanium-dioxide")["us"]["reliance"],
                         {"commodity": "Titanium sponge metal", "detail": detail, "value": "100"})

    def test_import_groups(self):
        groups = self.entry("cobalt")["us"]["imports"]
        self.assertEqual(groups[0], {"detail": "Cobalt metal", "years": "2021–24",
                                     "leader": {"country": "Norway", "value": "40"}, "top3": "80.0",
                                     "hhi_low": "2600", "hhi_high": "3000", "named_share": "80.0", "reason": None})
        self.assertEqual(groups[1], {"detail": "Cobalt oxide", "years": "2021–24", "leader": None, "top3": None,
                                     "hhi_low": None, "hhi_high": None, "named_share": None,
                                     "reason": "A named source is printed as “W”"})
        rare = self.entry("rare-earths")["us"]["imports"]
        self.assertEqual(rare[0]["leader"], {"country": "China", "value": "70"})
        self.assertIsNone(rare[0]["top3"])  # Only two named sources.
        self.assertEqual((rare[0]["named_share"], rare[0]["hhi_low"], rare[0]["hhi_high"]), ("83.0", "5069", "5358"))
        self.assertEqual((rare[1]["named_share"], rare[1]["hhi_low"], rare[1]["hhi_high"]), ("93.0", "8649", "8698"))

    def test_secondary_production(self):
        self.assertEqual(self.entry("copper")["us"]["secondary"],
                         [{"detail": "Secondary production (new and old scrap)", "unit": "thousand metric tons",
                           "value": "820"},
                          {"detail": "Recovered from scrap, old", "unit": "thousand metric tons", "value": "W"}])


if __name__ == "__main__":
    unittest.main()

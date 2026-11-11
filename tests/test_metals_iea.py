import copy
import unittest

import metals_fakes
from second_order import metals_iea

DEMAND, SUPPLY = metals_fakes.IEA_DEMAND_SHEET, metals_fakes.IEA_SUPPLY_SHEET


def read(sheets=None):
    sheets = sheets or metals_fakes.iea_sheets()
    return metals_iea.read(sheets[DEMAND], sheets[SUPPLY])


def mineral(key, minerals=None):
    return next(item for item in (minerals or read()) if item["id"] == key)


class MetalsIeaTests(unittest.TestCase):
    def test_six_minerals_with_usgs_chapter(self):
        minerals = read()
        self.assertEqual([item["id"] for item in minerals], list(metals_iea.MINERALS))
        chapters = {item["id"]: item["chapter"] for item in minerals}
        self.assertEqual(chapters, {"copper": "copper", "cobalt": "cobalt", "lithium": "lithium", "nickel": "nickel",
                                    "magnet-rare-earths": "rare-earths", "graphite": "graphite-natural"})
        self.assertEqual(mineral("graphite", minerals)["name"], "Graphite (all grades: natural and synthetic)")

    def test_stored_is_shortest_round_trip(self):
        self.assertEqual(metals_iea.stored("0.28799999999999998"), "0.288")
        self.assertEqual(metals_iea.stored("5.8500000000000002E-3"), "0.00585")
        self.assertEqual(metals_iea.stored("69.099999999999994"), "69.1")
        self.assertEqual(metals_iea.stored("1E+2"), "100")
        for bad in ("nan", "inf", "1e999", "-1e999", "1_0", "", "abc"):
            with self.assertRaises(metals_iea.IeaRefused):
                metals_iea.stored(bad)

    def test_energy_share_and_demand_rows(self):
        cobalt = mineral("cobalt")
        self.assertEqual(cobalt["demand"]["energy_share"]["2025"], "34.9")
        self.assertIn("steps-2040", cobalt["demand"]["energy_share"])
        self.assertEqual(len(cobalt["demand"]["energy_share"]), 16)
        rows = cobalt["demand"]["rows"]
        self.assertEqual([row["label"] for row in rows][-2:], ["Other uses", "Total demand"])
        self.assertEqual(rows[-1]["values"]["2025"], "259")
        self.assertEqual(rows[3]["values"]["2025"], "0.00972")
        self.assertEqual(set(rows[0]["values"]) - {"2025"},
                         {f"{s}-{y}" for s in ("cps", "steps", "hd") for y in range(2030, 2055, 5)})

    def test_supply_shares_of_printed_total(self):
        mining, refining = mineral("cobalt")["supply"]
        self.assertEqual(mining["total"]["2025"], "320")
        congo = mining["countries"][0]
        self.assertEqual(congo["country"], "Democratic Republic of Congo")
        self.assertEqual(congo["shares"]["2025"], "65.6")
        self.assertEqual(refining["countries"][0]["shares"]["2025"], "75.6")
        self.assertEqual(refining["total_label"], "Total clean technologies")
        self.assertEqual(mining["total_label"], "Total")
        self.assertEqual(mining["top3_published"]["2025"], "83")
        self.assertEqual(refining["top3_published"]["2025"], "86.8")
        self.assertEqual(set(congo["values"]), {"2025", "2030", "2035", "2040"})

    def test_shares_keep_one_decimal(self):
        alpha = mineral("copper")["supply"][0]["countries"][0]
        self.assertEqual(alpha["values"]["2025"], "50")
        self.assertEqual(alpha["shares"]["2025"], "50.0")
        self.assertEqual(mineral("copper")["supply"][0]["rest"]["shares"]["2025"], "10.0")

    def test_rest_of_world_is_not_a_country(self):
        for block in mineral("cobalt")["supply"]:
            self.assertNotIn("Rest of world", [item["country"] for item in block["countries"]])
            self.assertEqual(set(block["rest"]), {"values", "shares"})
        self.assertEqual(mineral("cobalt")["supply"][0]["rest"]["values"]["2025"], "38.6")
        self.assertEqual(len(mineral("cobalt")["supply"][0]["countries"]), 6)

    def test_graphite_blocks_keep_their_printed_titles(self):
        stages = [block["stage"] for block in mineral("graphite")["supply"]]
        self.assertEqual(stages, ["Graphite - Mining (natural)", "Graphite - Battery grade"])

    def test_layout_mismatch_refuses(self):
        sheets = metals_fakes.iea_sheets()
        sheets[DEMAND]["J4"] = "Stated Policies"
        with self.assertRaises(metals_iea.IeaRefused) as caught:
            read(sheets)
        self.assertEqual(caught.exception.place, DEMAND + "!J4")
        sheets = metals_fakes.iea_sheets()
        sheets[SUPPLY]["E4"] = "2045"
        with self.assertRaises(metals_iea.IeaRefused) as caught:
            read(sheets)
        self.assertEqual(caught.exception.place, SUPPLY + "!E4")
        sheets = metals_fakes.iea_sheets()
        cell = next(ref for ref, text in sheets[SUPPLY].items() if text == "Top 3 share" and ref.startswith("A"))
        del sheets[SUPPLY][cell]
        with self.assertRaises(metals_iea.IeaRefused):
            read(sheets)

    def test_other_refusals(self):
        def refused(change):
            sheets = metals_fakes.iea_sheets()
            change(sheets)
            with self.assertRaises(metals_iea.IeaRefused):
                read(sheets)
        refused(lambda s: s[DEMAND].update(A90="Cobalt"))  # The title twice.
        refused(lambda s: s[SUPPLY].update(A100="Cobalt - Mining"))
        refused(lambda s: s[SUPPLY].update(G6="Copper - Refinery"))
        refused(lambda s: s[DEMAND].update(B8="n/a"))
        refused(lambda s: s[SUPPLY].update(A2="Total supply"))

    def test_notes_verbatim_in_row_order(self):
        copper = mineral("copper")
        self.assertEqual(copper["notes"], {"demand": [metals_fakes.IEA_NOTES_DEMAND],
                                           "supply": metals_fakes.IEA_NOTES_SUPPLY})

    def test_scope_notes(self):
        minerals = read()
        for key in ("magnet-rare-earths", "graphite", "lithium"):
            self.assertTrue(mineral(key, minerals)["scope_note"])
        self.assertIn("never compared", mineral("magnet-rare-earths", minerals)["scope_note"])
        self.assertIsNone(mineral("copper", minerals)["scope_note"])
        self.assertIsNone(mineral("cobalt", minerals)["scope_note"])

    def test_read_does_not_change_its_input(self):
        sheets = metals_fakes.iea_sheets()
        before = copy.deepcopy(sheets)
        read(sheets)
        self.assertEqual(sheets, before)


if __name__ == "__main__":
    unittest.main()

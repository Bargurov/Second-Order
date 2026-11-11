import unittest

import metals_fakes
from second_order import metals_iea_uses
from second_order.metals_iea_uses import IeaUsesRefused
from second_order.thesis_workbook import Number

MINERAL, TECH = metals_iea_uses.BY_MINERAL, metals_iea_uses.BY_TECH


def read(sheets=None):
    sheets = sheets or metals_fakes.iea_uses_sheets()
    return metals_iea_uses.read(sheets[MINERAL], sheets[TECH])


def entry(name, entries=None):
    return next(item for item in (entries or read()) if item["name"] == name)


class MetalsIeaUsesTests(unittest.TestCase):
    def test_mapping_skips_boron_and_total(self):
        names = [item["name"] for item in read()]
        self.assertEqual(names, ["Cadmium", "Copper", "Iridium", "PGMs (other than iridum)", "Lithium", "Neodymium",
                                 "Total rare earth elements"])
        self.assertEqual(entry("Copper")["chapter"], "copper")
        self.assertIsNone(entry("Copper")["scope_note"])
        self.assertEqual(entry("Lithium")["scope_note"], "lithium content")
        self.assertEqual(entry("Total rare earth elements")["chapter"], "rare-earths")
        self.assertEqual(entry("Iridium")["chapter"], "platinum-group-metals")

    def test_total_keys_and_stored_values(self):
        total = entry("Copper")["total"]
        self.assertEqual(list(total), ["2025"] + [s + "-" + y for s in ("cps", "steps", "hd")
                                                  for y in ("2030", "2035", "2040", "2045", "2050")])
        self.assertEqual(total["2025"], "1000")
        self.assertEqual(total["cps-2030"], "1100")
        self.assertEqual(total["hd-2050"], "2500")

    def test_technologies_with_shares(self):
        techs = entry("Copper")["technologies"]
        self.assertEqual([item["label"] for item in techs], ["Wind", "Other low emissions power generation"])
        self.assertEqual([item["share_2025"] for item in techs], ["10.0", "25.0"])
        self.assertEqual(techs[0]["values"]["2025"], "100")
        self.assertEqual(techs[0]["values"]["steps-2035"], "170")

    def test_total_label_case_is_ignored(self):
        self.assertEqual([item["label"] for item in entry("Lithium")["technologies"]],
                         ["Electric vehicles", "Grid battery storage"])

    def test_block_with_zero_total_has_null_shares(self):
        techs = entry("Neodymium")["technologies"]
        self.assertEqual(techs[0]["share_2025"], None)
        self.assertEqual(techs[0]["values"]["2025"], "0")

    def test_pgm_entries_have_no_technologies(self):
        self.assertIsNone(entry("Iridium")["technologies"])
        self.assertIsNone(entry("PGMs (other than iridum)")["technologies"])

    def test_missing_block_gives_null_technologies(self):
        self.assertIsNone(entry("Cadmium")["technologies"])

    def refused(self, mutate, place, sheet=None):
        sheets = metals_fakes.iea_uses_sheets()
        mutate(sheets)
        with self.assertRaises(IeaUsesRefused) as raised:
            read(sheets)
        self.assertEqual(raised.exception.place, place)

    def test_layout_mismatches_refuse_with_place(self):
        self.refused(lambda s: s[MINERAL].update(A3="Something else"), MINERAL + "!A3")
        self.refused(lambda s: s[TECH].update(A2="Something else"), TECH + "!A2")
        self.refused(lambda s: s[MINERAL].update(J5="Stated"), MINERAL + "!J5")
        self.refused(lambda s: s[TECH].update(P4="Nope"), TECH + "!P4")
        self.refused(lambda s: s[MINERAL].update(N6="2051"), MINERAL + "!N6")
        self.refused(lambda s: s[TECH].update(B5="2024"), TECH + "!B5")

    def test_non_number_value_refuses(self):
        self.refused(lambda s: s[MINERAL].update(D10="abc"), MINERAL + "!D10")
        self.refused(lambda s: s[TECH].update(E8="n/a"), TECH + "!E8")

    def test_mapped_row_without_a_number_refuses(self):
        self.refused(lambda s: s[MINERAL].pop("B10"), MINERAL + "!B10")
        self.refused(lambda s: s[MINERAL].update(T10="n/a"), MINERAL + "!T10")

    def test_mapped_name_twice_refuses(self):
        self.refused(lambda s: s[MINERAL].update(A16="Copper"), MINERAL + "!A16")

    def test_a_label_the_mapping_does_not_hold_refuses(self):
        # Only Boron and the sheet's Total are skipped by name: a renamed or added IEA mineral refuses the part.
        self.refused(lambda s: s[MINERAL].update(A12="Mystery metal"), MINERAL + "!A12")
        with self.assertRaises(IeaUsesRefused) as raised:
            sheets = metals_fakes.iea_uses_sheets()
            sheets[MINERAL]["A9"] = "Cadmium (refined)"
            read(sheets)
        self.assertEqual((raised.exception.place, raised.exception.rule),
                         (MINERAL + "!A9", "is not a mineral this version maps"))

    def test_block_without_total_refuses(self):
        def drop_total(sheets):
            del sheets[TECH]["A10"]
        self.refused(drop_total, TECH + "!A13")

    def test_total_of_another_name_refuses(self):
        self.refused(lambda s: s[TECH].update(A10="Total Zinc"), TECH + "!A10")

    def test_block_total_differing_from_its_mineral_row_refuses(self):
        # Copper's 3.1 block ends on row 10; column M is steps-2045. The shares divide by this row, which the reply does
        # not carry, so it must be the 3.2 row the reply does carry, on every key.
        sheets = metals_fakes.iea_uses_sheets()
        self.assertEqual(sheets[TECH]["A10"], "Total Copper")
        self.refused(lambda s: s[TECH].update(M10=Number("1234")), TECH + "!M10")
        self.refused(lambda s: s[TECH].update(B10=Number("999")), TECH + "!B10")
        with self.assertRaises(IeaUsesRefused) as raised:
            read({**sheets, TECH: {**sheets[TECH], "M10": Number("1234")}})
        self.assertEqual(raised.exception.rule, "the block total differs from the mineral's row in sheet 3.2")
        self.assertNotIn("1234", str(raised.exception))

    def test_a_block_that_attaches_to_no_entry_is_not_compared(self):
        # "PGMs" names neither 3.2 PGM row (ruling R4), so its total is not held to one.
        sheets = metals_fakes.iea_uses_sheets()
        row = next(ref[1:] for ref, text in sheets[TECH].items() if text == "Total PGMs")
        sheets[TECH]["B" + row] = Number("31")
        self.assertIsNone(entry("PGMs (other than iridum)", read(sheets))["technologies"])


if __name__ == "__main__":
    unittest.main()

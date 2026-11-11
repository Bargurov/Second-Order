import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

from second_order.fuels_sources import (PAGES, ROLES, ROUTES, SCOPE, SERIES, FuelsRefused, attribution,
                                        check_sources, load_sources, record_for)


class FuelsSourcesTests(unittest.TestCase):
    def test_the_committed_record_passes(self):
        record, digest = load_sources()
        self.assertEqual([s["role"] for s in record["series"]], list(ROLES))
        self.assertEqual({s["series_id"] for s in record["series"]}, set(SERIES.values()))
        self.assertTrue(all(s["scope"] == SCOPE and s["public"] == "not_assessed" for s in record["series"]))
        self.assertEqual([(s["eia_route"], s["url"]) for s in record["series"]],
                         [(ROUTES[role], PAGES[role]) for role in ROLES])
        self.assertTrue(all(s["cadence"] == "daily" for s in record["series"]))
        self.assertRegex(digest, "^[0-9a-f]{64}$")

    def test_only_henry_hub_names_a_data_vendor_and_no_series_is_called_public_domain(self):
        """EIA names Refinitiv (LSEG) as the source of the Henry Hub spot price; its petroleum spot notes name none.
        No basis claims the series are in the public domain."""
        record, _ = load_sources()
        vendors = {s["role"]: s["data_vendor"] for s in record["series"]}
        self.assertEqual(vendors["henry_hub"], {"name": "Refinitiv, an LSEG business", "term": "eia-gas-price-notes"})
        self.assertTrue(all(vendors[role] is None for role in ROLES if role != "henry_hub"))
        for entry in record["series"]:
            self.assertIn("does not call it public domain", entry["basis"])
            self.assertIn("may be protected", entry["basis"])

    def test_refusals(self):
        record, _ = load_sources()
        changes = (lambda r: r.update(credit=r["credit"].replace("not ", "")),
                   lambda r: r["series"][0].update(public="assessed"),
                   lambda r: r["series"][0].update(scope="public"),
                   lambda r: r["series"].pop(),
                   lambda r: r["series"][0].update(extra=1),
                   lambda r: r["series"][1].update(series_id="RBRTE"),
                   lambda r: r["series"][4].update(series_id="RNGWHHD_FUTURES"),  # never a futures contract
                   lambda r: r["series"][4].update(eia_route="petroleum/pri/spt"),
                   lambda r: r["series"][0].update(url="https://fred.stlouisfed.org/series/DCOILBRENTEU"),
                   lambda r: r["series"][0].update(eia_units=""),
                   lambda r: r["series"][0].update(eia_units="dollars per barrel"),
                   lambda r: r["series"][0].update(eia_description=""),
                   lambda r: r["series"][0].update(cadence="weekly"),
                   lambda r: r["series"][4].update(data_vendor={"name": "LSEG", "term": "eia-petroleum-spot-notes"}),
                   lambda r: r["series"][4].update(data_vendor={"name": "", "term": "eia-gas-price-notes"}),
                   lambda r: r["series"][4].update(data_vendor="Refinitiv"),
                   lambda r: r["series"][0].update(terms=["unlisted"]),
                   lambda r: r["terms"][0].update(url="http://www.eia.gov/about/copyrights_reuse.php"),
                   lambda r: r["terms"].append(dict(r["terms"][0])),
                   lambda r: r.update(page_label="Public"),
                   lambda r: r["series"][0].update(unit=[]),
                   lambda r: r["series"][0].update(unit={}),
                   lambda r: r["series"][0].update(terms=[["eia-reuse"]]),
                   lambda r: r["terms"][0].update(id=[]))
        for number, change in enumerate(changes):
            with self.subTest(number=number):
                copy_ = copy.deepcopy(record)
                change(copy_)
                with self.assertRaises(FuelsRefused) as caught:
                    check_sources(copy_)
                self.assertEqual(caught.exception.status, 500)
        with self.assertRaises(FuelsRefused) as caught:
            check_sources([])
        self.assertEqual(caught.exception.status, 500)

    def test_a_refusal_names_the_field_not_the_value(self):
        record, _ = load_sources()
        record["series"][0]["scope"] = "secret-value-xyz"
        with self.assertRaises(FuelsRefused) as caught:
            check_sources(record)
        self.assertIn("scope", str(caught.exception))
        self.assertNotIn("secret-value-xyz", str(caught.exception))

    def test_a_missing_record_is_503(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FuelsRefused) as caught:
                load_sources(Path(folder))
        self.assertEqual(caught.exception.status, 503)

    def test_a_record_that_is_not_json_is_500(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "sources.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(FuelsRefused) as caught:
                load_sources(Path(folder))
        self.assertEqual(caught.exception.status, 500)

    def test_attribution_names_eia_the_series_the_retrieval_date_and_the_vendor_where_eia_names_one(self):
        sources = load_sources()[0]
        brent = record_for(sources, "RBRTE")
        self.assertEqual(attribution(brent, date(2026, 11, 6)),
                         "Source: U.S. Energy Information Administration, Europe Brent Spot Price FOB (Dollars per "
                         "Barrel) [RBRTE], retrieved November 6, 2026; https://www.eia.gov/dnav/pet/hist/RBRTED.htm.")
        self.assertEqual(attribution(brent, None),
                         "Source: U.S. Energy Information Administration, Europe Brent Spot Price FOB (Dollars per "
                         "Barrel) [RBRTE]; https://www.eia.gov/dnav/pet/hist/RBRTED.htm.")
        self.assertTrue(attribution(record_for(sources, "RNGWHHD"), date(2026, 11, 1)).endswith(
            "; https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm. Data: Refinitiv, an LSEG business, as EIA states."))

if __name__ == "__main__":
    unittest.main()

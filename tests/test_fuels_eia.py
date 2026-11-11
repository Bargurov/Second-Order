"""The EIA importer on synthetic replies (tests/fuels_fakes.py): the key never kept or shown, whole histories only, the
series and units the record names, dates kept apart, refusals per series and aborts that write nothing."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import quote
import tempfile
import unittest
from fuels_fakes import FAKE_KEY, RETRIEVED, RETRIEVED_ON, FakeEia, datasets, write_snapshot
from second_order import fuels_eia, fuels_snapshots, fuels_sources
from second_order.fred import ImportRefused
from second_order.fuels_eia import refresh

CONTENT = fuels_sources.CONTENT_DIR
IDS = ["RBRTE", "RWTC", "EER_EPMRU_PF4_Y35NY_DPG", "EER_EPD2DXL0_PF4_Y35NY_DPG", "RNGWHHD"]
GAS = "EER_EPMRU_PF4_Y35NY_DPG"
SECRETS = (FAKE_KEY, quote(FAKE_KEY, safe=""))
START = (RETRIEVED_ON - timedelta(days=400)).isoformat()  # 2025-10-02


class EiaImportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.snapshots = Path(self._tmp.name) / "snapshots"

    def run_refresh(self, fake, clock=RETRIEVED, start=None):
        return refresh(self.snapshots, CONTENT, FAKE_KEY, start, fake.client(), lambda: clock)

    def latest(self):
        return fuels_snapshots.load_all(self.snapshots)["snapshots"][-1]

    def files(self):
        return list(self.snapshots.glob("*")) if self.snapshots.exists() else []

    def assertNoSecret(self, text: str):
        for secret in SECRETS:
            self.assertNotIn(secret, text)

    def refused(self, report, series_id, *phrases):
        entry = report["series"][series_id]
        self.assertEqual((entry["state"], entry["rows"]), ("refused", 0), entry)
        for phrase in phrases:
            self.assertIn(phrase, entry["problem"])
        self.assertEqual(self.latest()["series"][series_id]["observations"], [])
        stored = [s for s in IDS if s != series_id]
        self.assertEqual([report["series"][s]["state"] for s in stored], ["stored"] * len(stored))
        return entry["problem"]

    # ---- what is kept

    def test_five_series_are_stored_with_their_dates_kept_apart(self):
        fake = FakeEia(datasets())
        report = self.run_refresh(fake)
        snap = self.latest()
        self.assertEqual((snap["snapshot_version"], snap["provider"], snap["adapter_version"]),
                         ("fuels-snapshot-0.2", "eia", "fuels-eia-0.1"))
        brent = snap["series"]["RBRTE"]
        self.assertEqual(brent["observations"][-1], ["2026-11-03", "80.00"])
        self.assertEqual((snap["retrieved_at"], snap["retrieved_on"], snap["observation_end"]),
                         (RETRIEVED.isoformat(), "2026-11-06", "2026-11-06"))
        self.assertEqual(snap["observation_start"], (RETRIEVED_ON - timedelta(days=400)).isoformat())
        self.assertEqual(list(report["series"]), IDS)
        self.assertTrue(all(s["state"] == "stored" for s in snap["series"].values()))
        self.assertEqual((report["requests"], len(fake.calls)), (5, 5))  # one page each

    def test_no_publication_date_is_inferred(self):
        """EIA's API gives no publication date: none is stored, from the observation date or the retrieval."""
        report = self.run_refresh(FakeEia(datasets()))
        snap = self.latest()
        for series_id, entry in snap["series"].items():
            self.assertEqual((entry["release"], entry["release_dates"]), (None, []))
            self.assertIsNone(fuels_snapshots.published_on(entry, date(2026, 11, 3)))
            self.assertIsNone(report["series"][series_id]["publication_date"])
        self.assertIn("never inferred", snap["semantics"]["eia_publication_date"])
        self.assertIn("not a record of what was known", snap["semantics"]["history"])

    def test_each_request_asks_for_the_daily_series_in_the_window_in_period_order(self):
        fake = FakeEia(datasets())
        self.run_refresh(fake)
        routes = {series: route for route, series, _ in fake.calls}
        self.assertEqual(routes, {r["series_id"]: r["eia_route"] for r in fuels_sources.load_sources()[0]["series"]})
        for _, series, params in fake.calls:
            self.assertEqual(params, {"frequency": "daily", "data[0]": "value", "facets[series][]": series,
                                      "start": START, "end": "2026-11-06", "sort[0][column]": "period",
                                      "sort[0][direction]": "asc", "length": "5000", "offset": "0"})

    def test_the_new_york_date_ends_the_window(self):
        late = datetime(2026, 11, 7, 3, tzinfo=timezone.utc)  # 22:00 on 6 Nov in New York
        fake = FakeEia(datasets())
        report = self.run_refresh(fake, late)
        self.assertEqual(report["retrieved_on"], "2026-11-06")
        self.assertEqual({params["end"] for _, _, params in fake.calls}, {"2026-11-06"})

    def test_a_missing_value_is_stored_as_none(self):
        data = datasets()
        data["RWTC"][-1] = (data["RWTC"][-1][0], None)
        self.run_refresh(FakeEia(data))
        self.assertEqual(self.latest()["series"]["RWTC"]["observations"][-1], ["2026-11-03", None])

    def test_numbers_are_kept_as_the_exact_text_eia_sent(self):
        self.run_refresh(FakeEia(datasets(), numbers=True, total_as_number=True))
        snap = self.latest()
        self.assertEqual(snap["series"]["RBRTE"]["observations"][-1], ["2026-11-03", "80.0"])
        self.assertEqual(snap["series"][GAS]["observations"][-2], ["2026-11-02", "2.501"])

    def test_terms_and_eia_metadata_are_copied_into_the_snapshot(self):
        self.run_refresh(FakeEia(datasets()))
        sources, sha = fuels_sources.load_sources(CONTENT)
        snap = self.latest()
        self.assertEqual(snap["sources_sha256"], sha)
        for series_id, entry in snap["series"].items():
            record = fuels_sources.record_for(sources, series_id)
            self.assertEqual(entry["terms"], record)
            self.assertEqual({k: entry["metadata"][k] for k in ("route", "series", "description", "units", "frequency",
                                                                 "pages", "api_version")},
                             {"route": record["eia_route"], "series": series_id,
                              "description": record["eia_description"], "units": record["eia_units"],
                              "frequency": "daily", "pages": 1, "api_version": "SYNTHETIC-2.1"})
            self.assertEqual(len(entry["responses_sha256"]), 1)

    def test_a_second_refresh_appends_and_the_helper_returns_the_stored_id(self):
        first = write_snapshot(self.snapshots)
        self.assertEqual(self.latest()["snapshot_id"], first)
        report = self.run_refresh(FakeEia(datasets()), RETRIEVED + timedelta(hours=1))
        self.assertTrue(report["created"])
        self.assertEqual(len(fuels_snapshots.load_all(self.snapshots)["snapshots"]), 2)

    def test_the_report_carries_dates_and_counts_but_no_values(self):
        report = self.run_refresh(FakeEia(datasets()))
        brent = report["series"]["RBRTE"]
        self.assertEqual((brent["state"], brent["last_date"], brent["publication_date"]), ("stored", "2026-11-03", None))
        self.assertGreaterEqual(brent["first_date"], START)
        self.assertNotIn("80.00", json.dumps(report))

    # ---- the key

    def test_the_key_echoed_in_request_params_is_never_kept(self):
        fake = FakeEia(datasets())
        report = self.run_refresh(fake)
        self.assertEqual(set(fake.keys), {FAKE_KEY})
        for path in self.files():
            self.assertNoSecret(path.read_text(encoding="utf-8"))
        self.assertNoSecret(json.dumps(report))
        self.assertNoSecret(json.dumps(self.latest()))
        self.assertTrue(any(FAKE_KEY in url for url in fake.urls))  # the request did carry it, as EIA requires

    def test_a_reply_with_the_key_anywhere_else_aborts_and_writes_nothing(self):
        fake = FakeEia(datasets(), extra={"RWTC": {"description": "SYNTHETIC echo of {KEY}"}})
        with self.assertRaises(ImportRefused) as raised:
            self.run_refresh(fake)
        self.assertIn("credential", str(raised.exception))
        self.assertNoSecret(str(raised.exception))
        self.assertEqual(self.files(), [])

    def test_an_error_reply_that_holds_the_key_is_reported_by_status_and_code_only(self):
        body = {"error": {"code": "API_KEY_INVALID", "message": "The key {KEY} is not valid"}}
        with self.assertRaises(ImportRefused) as raised:
            self.run_refresh(FakeEia(datasets(), status={"RBRTE": (403, body)}))
        self.assertEqual(str(raised.exception), "EIA request for RBRTE returned HTTP 403 (API_KEY_INVALID)")
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(self.files(), [])
        coded = {"error": {"code": "{KEY}", "message": "{KEY}"}}  # a "code" that is the key is never quoted
        with self.assertRaises(ImportRefused) as raised:
            self.run_refresh(FakeEia(datasets(), status={"RBRTE": (401, coded)}))
        self.assertEqual(str(raised.exception), "EIA request for RBRTE returned HTTP 401")

    def test_a_network_error_names_only_its_type(self):
        """httpx puts the request URL, and so the key, in the error text: only the error's type is reported."""
        with self.assertRaises(ImportRefused) as raised:
            self.run_refresh(FakeEia(datasets(), raise_for=GAS))
        self.assertEqual(str(raised.exception), f"EIA request for {GAS} failed (ConnectError)")
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(self.files(), [])

    def test_a_reply_that_is_not_json_refuses_the_series_unless_it_holds_the_key(self):
        report = self.run_refresh(FakeEia(datasets(), raw={"RNGWHHD": "<html>SYNTHETIC maintenance page</html>"}))
        self.refused(report, "RNGWHHD", "not JSON")
        with self.assertRaises(ImportRefused) as raised:
            self.run_refresh(FakeEia(datasets(), raw={"RNGWHHD": "<html>{KEY}</html>"}), RETRIEVED + timedelta(minutes=1))
        self.assertIn("credential", str(raised.exception))
        self.assertNoSecret(str(raised.exception))
        self.assertEqual(len(self.files()), 1)  # only the first refresh's snapshot

    # ---- provider errors

    def test_a_server_error_or_rate_limit_aborts_and_writes_nothing(self):
        for code in (500, 503, 429):
            with self.subTest(code=code):
                with self.assertRaises(ImportRefused) as raised:
                    self.run_refresh(FakeEia(datasets(), status={"RWTC": (code, {"error": "SYNTHETIC"})}))
                self.assertIn(f"HTTP {code}", str(raised.exception))
                self.assertEqual(self.files(), [])

    def test_another_http_error_refuses_only_that_series(self):
        body = {"error": {"code": "INVALID_ROUTE", "message": "No route for {KEY}"}}
        report = self.run_refresh(FakeEia(datasets(), status={"RNGWHHD": (404, body)}))
        problem = self.refused(report, "RNGWHHD", "HTTP 404", "INVALID_ROUTE")
        self.assertNoSecret(problem)

    def test_a_reply_that_is_not_json_refuses_that_series(self):
        report = self.run_refresh(FakeEia(datasets(), status={"RWTC": (404, "not json")}))
        self.refused(report, "RWTC", "HTTP 404")

    # ---- whole histories only

    def test_a_paged_history_is_kept_whole(self):
        whole = FakeEia(datasets())
        self.run_refresh(whole)
        expected = {s: e["observations"] for s, e in self.latest()["series"].items()}
        paged = FakeEia(datasets(), page_cap=100)
        report = self.run_refresh(paged, RETRIEVED + timedelta(minutes=5))
        snap = self.latest()
        self.assertEqual({s: e["observations"] for s, e in snap["series"].items()}, expected)
        self.assertEqual(report["requests"], len(paged.calls))
        self.assertGreater(report["requests"], 5)
        brent = [int(p["offset"]) for _, s, p in paged.calls if s == "RBRTE"]
        self.assertEqual(brent, list(range(0, len(expected["RBRTE"]), 100)))
        self.assertEqual(snap["series"]["RBRTE"]["metadata"]["pages"], len(brent))
        self.assertEqual(len(snap["series"]["RBRTE"]["responses_sha256"]), len(brent))

    def test_a_reply_that_ends_before_its_stated_total_is_refused(self):
        report = self.run_refresh(FakeEia(datasets(), page_cap=100, truncate={"RBRTE"}))
        self.refused(report, "RBRTE", "ended at 100 of")

    def test_a_warning_refuses_the_series(self):
        report = self.run_refresh(FakeEia(datasets(), warn={GAS}))
        self.refused(report, GAS, "warning")

    def test_overlapping_pages_are_refused(self):
        report = self.run_refresh(FakeEia(datasets(), page_cap=100, overlap={"RWTC"}))
        self.refused(report, "RWTC", "overlap")

    def test_a_stated_total_that_does_not_match_the_rows_is_refused(self):
        count = len([d for d, _ in datasets()["RWTC"] if d.isoformat() >= START])
        short = self.run_refresh(FakeEia(datasets(), total={"RWTC": count + 3}))
        self.refused(short, "RWTC", f"ended at {count} of {count + 3}")
        over = self.run_refresh(FakeEia(datasets(), total={"RWTC": count - 1}), RETRIEVED + timedelta(minutes=1))
        self.refused(over, "RWTC", "more rows")

    def test_a_missing_or_unreadable_total_is_refused(self):
        for total in (None, "", "12a", "-1", "١٢"):  # the last: Arabic-Indic digits
            with self.subTest(total=total), tempfile.TemporaryDirectory() as tmp:
                self.snapshots = Path(tmp) / "snapshots"
                report = self.run_refresh(FakeEia(datasets(), total={"RWTC": total}))
                self.refused(report, "RWTC", "states no row count")

    def test_more_rows_than_the_window_has_days_are_refused(self):
        report = self.run_refresh(FakeEia(datasets(), total={"RWTC": 402}))  # 2025-10-02 to 2026-11-06: 401 days
        self.refused(report, "RWTC", "more than the requested window can hold (401 days)")

    def test_a_long_window_is_not_refused_for_its_length(self):
        """--start may reach years back: the bound is the window's days, not a fixed count."""
        start = date(2010, 1, 4)
        data = {series: [(start + timedelta(days=n), "1.00") for n in range(6000)
                         if (start + timedelta(days=n)).weekday() < 5 and start + timedelta(days=n) <= date(2026, 11, 3)]
                for series in datasets()}
        paged = FakeEia(data)
        report = self.run_refresh(paged, start=start)
        self.assertEqual({e["state"] for e in report["series"].values()}, {"stored"})
        self.assertGreater(report["series"]["RBRTE"]["rows"], 4000)
        self.assertEqual([p["offset"] for _, s, p in paged.calls if s == "RBRTE"], ["0"])  # under 5,000: one page

    def test_an_empty_series_is_refused(self):
        data = datasets()
        data["RNGWHHD"] = []
        report = self.run_refresh(FakeEia(data))
        self.refused(report, "RNGWHHD", "no observations")

    # ---- the series the record names

    def test_rows_of_another_series_are_refused(self):
        report = self.run_refresh(FakeEia(datasets(), rows={"RNGWHHD": {"series": "RNGC1"}}))  # a futures contract
        self.refused(report, "RNGWHHD", "another series", "RNGC1")

    def test_another_description_or_units_are_refused_naming_both(self):
        described = self.run_refresh(FakeEia(datasets(), rows={"RBRTE": {"series-description": "Brent Futures"}}))
        self.refused(described, "RBRTE", "Brent Futures", "Europe Brent Spot Price FOB")
        units = self.run_refresh(FakeEia(datasets(), rows={GAS: {"units": "$/BBL"}}), RETRIEVED + timedelta(minutes=1))
        self.refused(units, GAS, "units changed", "$/BBL", "$/GAL")

    def test_a_reply_that_is_not_daily_is_refused(self):
        report = self.run_refresh(FakeEia(datasets(), frequency="weekly"))
        self.assertEqual({e["state"] for e in report["series"].values()}, {"refused"})
        self.assertIn("not daily", report["series"]["RBRTE"]["problem"])

    def test_a_period_that_is_not_a_day_in_the_window_is_refused(self):
        for period, phrase in (("2026-11", "not a day"), ("2026-02-30", "not a day"), (20261103, "not a day"),
                               ("2027-01-04", "outside the requested window")):
            with self.subTest(period=period), tempfile.TemporaryDirectory() as tmp:
                self.snapshots = Path(tmp) / "snapshots"
                report = self.run_refresh(FakeEia(datasets(), rows={"RWTC": {"period": period}}))
                self.assertEqual(report["series"]["RWTC"]["state"], "refused")
                self.assertIn(phrase, report["series"]["RWTC"]["problem"])

    def test_a_value_that_is_not_a_plain_decimal_refuses_only_that_series_without_quoting_it(self):
        for bad in ("abc", "nan", "inf", "", "1e2", "٨٠.٠٠", True, [], {"v": 1}):
            with self.subTest(value=bad), tempfile.TemporaryDirectory() as tmp:
                self.snapshots = Path(tmp) / "snapshots"
                data = datasets()
                data["RWTC"][-1] = (data["RWTC"][-1][0], bad)
                report = self.run_refresh(FakeEia(data))
                problem = self.refused(report, "RWTC", "not a plain decimal")
                if isinstance(bad, str) and bad:
                    self.assertNotIn(bad, problem)

    def test_the_start_must_precede_the_retrieval_date(self):
        with self.assertRaises(ImportRefused):
            self.run_refresh(FakeEia(datasets()), start=RETRIEVED_ON)
        self.assertEqual(self.files(), [])

    def test_without_a_key_nothing_is_requested(self):
        fake = FakeEia(datasets())
        with self.assertRaises(ImportRefused) as raised:
            refresh(self.snapshots, CONTENT, "", None, fake.client(), lambda: RETRIEVED)
        self.assertIn("EIA_API_KEY", str(raised.exception))
        self.assertEqual((fake.calls, self.files()), ([], []))

    def test_the_module_has_no_fred_request(self):
        source = Path(fuels_eia.__file__).read_text(encoding="utf-8")
        self.assertNotIn("stlouisfed", source)
        self.assertNotIn("fred.fetch", source)


if __name__ == "__main__":
    unittest.main()

"""Private market context for selected events: supported events, the context date and its convention, the view's
statuses and descriptive changes, retrieval versions, and local records that do not verify.

Every Board reply here is SYNTHETIC (tests/market_fakes.py: release packages of invented values in the Board's XML
format, served through an injected httpx.MockTransport), as is every CSV retrieval a test writes directly in the
earlier two-series format, and every folder is temporary. The committed case-library bundle is read in place by the
reuse tests, which check that it is unchanged afterwards. Nothing reaches a network.
"""
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest

import httpx

from market_fakes import (Clock, FakeRelease, board_csv, capture, fill_inbox, inbox_feeds, item_id, release_data,
                          release_zip, synthetic_pair, package_reply)
from second_order import event_context, market_context, market_retrieval, market_store
from second_order.event_context import CONVENTION, OUTSIDE_NOTE, UNSUPPORTED_CAPTURE
from second_order.market_context import ContextRefused

FEEDS = inbox_feeds(
    fed=[("FOMC statement", "Wed, 16 Sep 2026 18:00:00 GMT"), ("Late statement", "Thu, 17 Sep 2026 02:30:00 GMT"),
         ("Ambiguous zone", "Wed, 16 Sep 2026 18:00:00 XYZ"), ("June statement", "Wed, 18 Jun 2025 18:00:00 GMT")],
    empsit=[("Jobs report", "2026-10-02T08:30:00-04:00")], cpi=[("CPI report", "2026-09-11T08:30:00-04:00")],
    eia=[("Energy article", "Wed, 07 Oct 2026  09:00:00 EST")], wto=[("Trade news", "Thu, 08 Oct 2026 00:00:00 GMT")])
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)  # 11:00 in New York, a Friday.


def fingerprint(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in folder.rglob("*") if path.is_file()} if folder.exists() else {}


def writable(path: Path) -> None:
    path.chmod(stat.S_IWRITE | stat.S_IREAD)


class Folders(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.store, self.inbox, self.intake = self.root / "market", self.root / "inbox", self.root / "intake"
        self.clock = Clock(NOW)
        self.view = fill_inbox(self.inbox, FEEDS, self.clock)
        self.board = FakeRelease(self.clock)

    def id(self, title: str) -> str:  # noqa: A003 - an inbox item's ID by its title
        return item_id(self.view, title)

    def key(self, title: str) -> str:
        return event_context.event_key("inbox", self.id(title))

    def page(self, kind: str, event_id: str, bundle: Path | None = None) -> dict:
        return market_retrieval.event_page(kind, event_id, self.store, bundle, self.inbox, self.intake, None, self.clock)

    def confirm(self, title: str, day: str, version: int = 1, convention: str = CONVENTION["id"]) -> dict:
        body = json.dumps({"context_date": day, "convention": convention, "version": version}).encode()
        return event_context.confirm(self.id(title), body, self.store, self.inbox, self.clock)

    def fetch(self, *titles: str, board: FakeRelease | None = None) -> dict:
        keys = [self.key(title) for title in titles]
        plan = market_retrieval.plan_view(keys, self.store, None, self.inbox, self.intake, None, self.clock)
        body = json.dumps({"plan_sha256": plan["plan_sha256"], "events": keys, "attempt": plan["next_attempt"]})
        return market_retrieval.dispatch(body.encode(), self.store, None, self.inbox, self.intake,
                                         (board or self.board).fetcher(), self.clock)

    def day(self, view: dict, when: str) -> dict:
        return next(row for row in view["days"] if row["date"] == when)

    def put_retrieval(self, start: date, end: date, requested: datetime, overrides: dict | None = None) -> str:
        """A private CSV retrieval written directly, as an approved request for the earlier two-series download
        saved one."""
        data = board_csv(start, end, overrides)
        url = market_context.export_url(start, end)
        record = {"retrieval_version": market_store.RETRIEVAL_VERSION,
                  "retrieval_id": f"r{requested:%Y%m%dT%H%M%S%f}Z-{market_context.sha256(data)[:12]}",
                  "source": market_store.SOURCE_ID, "url": url, "requested_start": start.isoformat(),
                  "requested_end": end.isoformat(), "requested_at": requested.isoformat(timespec="seconds"),
                  "received_at": requested.isoformat(timespec="seconds"), "http_status": 200,
                  "content_type": "text/csv", "response_date": format_datetime(requested, usegmt=True),
                  "bytes": len(data), "sha256": market_context.sha256(data), "plan_sha256": "0" * 64, "attempt": 1,
                  "client": {"user_agent": "test", "transport": "SYNTHETIC: written directly by the test"}}
        return market_store.write_retrieval(self.store, record, data)


class SupportedEventTests(Folders):
    def test_only_fed_and_bls_entries_are_supported_and_the_others_are_explained(self):
        for title, family in (("FOMC statement", "Federal Reserve monetary policy"), ("Jobs report", "BLS employment"),
                              ("CPI report", "BLS inflation")):
            event = self.page("inbox", self.id(title))["event"]
            self.assertTrue(event["supported"], title)
            self.assertEqual(event["family_label"], family)
        for title in ("Energy article", "Trade news"):
            page = self.page("inbox", self.id(title))
            self.assertFalse(page["event"]["supported"])
            self.assertEqual(page["event"]["outside"], OUTSIDE_NOTE)
            self.assertIsNone(page["view"])
            self.assertIsNone(page["plan"])
            with self.assertRaises(ContextRefused) as refused:
                self.confirm(title, "2026-10-07")
            self.assertEqual((refused.exception.status, str(refused.exception)), (422, OUTSIDE_NOTE))
        self.assertFalse(self.store.exists())

    def test_a_capture_is_supported_by_its_official_link_and_keeps_its_supplied_time(self):
        cases = (("https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm", "fed-monetary"),
                 ("https://www.bls.gov/news.release/archives/empsit_10022026.htm", "bls-empsit"),
                 ("https://www.bls.gov/news.release/cpi.nr0.htm", "bls-cpi"),
                 ("https://www.eia.gov/todayinenergy/detail.php?id=90001", None),
                 ("https://www.federalreserve.gov/newsevents/speech/powell20260916a.htm", None))
        for n, (link, family) in enumerate(cases):
            with self.subTest(link=link):
                capture_id = capture(self.intake, f"Event {n}", link, "2026-09-16T14:00:00-04:00",
                                     NOW - timedelta(minutes=n))
                event = self.page("capture", capture_id)["event"]
                self.assertEqual(event["family"], family)
                self.assertEqual(event["outside"], None if family else UNSUPPORTED_CAPTURE)
                self.assertEqual(event["supplied"]["published_at_as_supplied"], "2026-09-16T14:00:00-04:00")
                self.assertEqual(event["context"] and event["context"]["date"], "2026-09-16" if family else None)

    def test_unknown_identifiers_are_refused(self):
        for kind, event_id in (("inbox", "fed-monetary:zz"), ("inbox", "nowhere:0123456789abcdef0123"),
                               ("inbox", "fed-monetary:0123456789abcdef0123"), ("capture", "../intake")):
            with self.subTest(event_id=event_id), self.assertRaises(ContextRefused) as refused:
                self.page(kind, event_id)
            self.assertEqual(refused.exception.status, 404)


class ContextDateTests(Folders):
    def test_an_inbox_entry_has_no_context_date_until_the_user_confirms_one(self):
        page = self.page("inbox", self.id("FOMC statement"))
        self.assertIsNone(page["event"]["context"])
        self.assertIsNone(page["view"])
        self.assertEqual(page["event"]["suggestion"]["date"], "2026-09-16")
        self.assertEqual(page["event"]["suggestion"]["new_york_time"], "14:00")
        self.assertIn("not a verified publication instant", page["event"]["suggestion"]["basis"])
        self.assertEqual(self.confirm("FOMC statement", "2026-09-16"), {"saved_now": True, "version": 1})
        context = self.page("inbox", self.id("FOMC statement"))["event"]["context"]
        self.assertEqual((context["date"], context["basis"], context["convention"]), ("2026-09-16", "confirmed",
                                                                                      CONVENTION))
        self.assertEqual(context["window"], {"start": "2026-09-02", "end": "2026-09-30", "days_before": 14,
                                             "days_after": 14})

    def test_the_suggestion_is_the_new_york_date_of_the_feed_instant(self):
        # 02:30 UTC on 17 September is 22:30 on 16 September in New York.
        suggestion = self.page("inbox", self.id("Late statement"))["event"]["suggestion"]
        self.assertEqual((suggestion["date"], suggestion["new_york_time"], suggestion["utc_offset"]),
                         ("2026-09-16", "22:30", "-04:00"))
        self.assertEqual(self.page("inbox", self.id("Jobs report"))["event"]["suggestion"]["date"], "2026-10-02")

    def test_a_timestamp_without_an_instant_offers_no_date_and_invents_none(self):
        event = self.page("inbox", self.id("Ambiguous zone"))["event"]
        self.assertIsNone(event["suggestion"])
        self.assertIn("XYZ", event["suggestion_problem"])
        self.confirm("Ambiguous zone", "2026-09-16")  # The user may still type the date they verified.
        self.assertEqual(self.page("inbox", self.id("Ambiguous zone"))["event"]["context"]["date"], "2026-09-16")

    def test_a_capture_context_date_is_the_new_york_date_of_its_supplied_instant(self):
        for supplied, expected in (("2026-09-17T02:30:00+00:00", "2026-09-16"), ("2026-09-16T23:30:00-04:00", "2026-09-16"),
                                   ("2026-09-17T09:00:00+09:00", "2026-09-16"), ("2026-03-08T06:30:00Z", "2026-03-08"),
                                   ("2026-03-08T04:30:00Z", "2026-03-07"), ("2025-11-02T03:30:00Z", "2025-11-01")):
            with self.subTest(supplied=supplied):
                capture_id = capture(self.intake, f"Statement {supplied}",
                                     "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
                                     supplied, NOW)
                self.clock.advance(seconds=1)
                event = self.page("capture", capture_id)["event"]
                self.assertEqual(event["context"]["date"], expected)
                self.assertEqual(event["context"]["basis"], "supplied")
                self.assertEqual(event["supplied"]["published_at_as_supplied"], supplied)

    def test_a_confirmation_needs_the_convention_a_real_past_date_and_the_expected_version(self):
        refusals = ((dict(day="2026-09-16", convention="utc-date"), 422), (dict(day="2026-9-16"), 422),
                    (dict(day="2026-02-30"), 422), (dict(day="2026-10-10"), 422), (dict(day="2026-09-16", version=2), 409))
        for arguments, status in refusals:
            with self.subTest(arguments=arguments), self.assertRaises(ContextRefused) as refused:
                self.confirm("FOMC statement", **arguments)
            self.assertEqual(refused.exception.status, status)
        self.assertFalse(self.store.exists())
        self.assertEqual(self.confirm("FOMC statement", "2026-10-09")["version"], 1)  # Today is allowed.

    def test_a_new_date_is_a_new_version_and_earlier_versions_stay_unchanged(self):
        self.confirm("FOMC statement", "2026-09-17")
        first = self.store / "events" / self.key("FOMC statement") / "1.json"
        before = first.read_bytes()
        self.assertEqual(self.confirm("FOMC statement", "2026-09-17", version=2), {"saved_now": False, "version": 1})
        self.assertEqual(self.confirm("FOMC statement", "2026-09-16", version=2), {"saved_now": True, "version": 2})
        self.assertEqual(first.read_bytes(), before)
        event = self.page("inbox", self.id("FOMC statement"))["event"]
        self.assertEqual([(item["version"], item["context_date"]) for item in event["confirmations"]],
                         [(1, "2026-09-17"), (2, "2026-09-16")])
        self.assertEqual((event["context"]["date"], event["context"]["version"]), ("2026-09-16", 2))
        with self.assertRaises(ContextRefused) as refused:  # A stale page cannot add a third version by accident.
            self.confirm("FOMC statement", "2026-09-18", version=2)
        self.assertEqual(refused.exception.status, 409)

    def test_a_confirmed_event_reopens_after_its_entry_leaves_the_inbox(self):
        self.confirm("FOMC statement", "2026-09-16")
        # The WTO feed's raw copies are kept read-only, so each is unlocked once before its removal is retried.
        shutil.rmtree(self.inbox, onexc=lambda remove, path, _: (writable(Path(path)), remove(path)))
        event = self.page("inbox", self.id("FOMC statement"))["event"]
        self.assertEqual((event["title"], event["in_inbox"], event["context"]["date"]),
                         ("FOMC statement", False, "2026-09-16"))

    def test_a_corrupted_confirmation_is_reported_left_unchanged_and_blocks_new_dates(self):
        self.confirm("FOMC statement", "2026-09-16")
        path = self.store / "events" / self.key("FOMC statement") / "1.json"
        writable(path)
        path.write_bytes(path.read_bytes().replace(b"2026-09-16", b"2026-09-1x"))
        before = fingerprint(self.store)
        page = self.page("inbox", self.id("FOMC statement"))
        self.assertIn("does not have the expected fields and values", page["event"]["problem"])
        self.assertIsNone(page["view"])
        with self.assertRaises(ContextRefused) as refused:
            self.confirm("FOMC statement", "2026-09-17", version=2)
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(fingerprint(self.store), before)


class ViewTests(Folders):
    def test_weekends_holidays_and_observed_sessions_are_distinguished(self):
        self.confirm("FOMC statement", "2026-09-16")
        self.fetch("FOMC statement")
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        statuses = {row["date"]: row["observations"]["RIFLGFCY02_N.B"]["status"] for row in view["days"]}
        self.assertEqual(statuses["2026-09-05"], "weekend")
        self.assertEqual(statuses["2026-09-07"], "calendar_holiday")  # Labor Day: the Board's row says ND.
        self.assertEqual(self.day(view, "2026-09-07")["observations"]["RIFLGFCY02_N.B"]["raw"], "ND")
        self.assertEqual(statuses["2026-09-08"], "session_value")
        self.assertEqual(len(view["days"]), 29)
        self.assertTrue(view["complete"])
        self.assertEqual(self.day(view, "2026-09-08")["observations"]["RIFLGFCY02_N.B"]["raw"],
                         synthetic_pair(date(2026, 9, 8))[0])

    def test_endpoints_follow_the_rule_and_changes_are_exact_basis_points(self):
        self.confirm("FOMC statement", "2026-09-16")
        overrides = {date(2026, 9, 15): ("3.94", "4.125"), date(2026, 9, 17): ("3.90", "4.10"),
                     date(2026, 9, 23): ("4.06", "4.125")}
        self.fetch("FOMC statement", board=FakeRelease(self.clock, overrides=overrides))
        endpoints = self.page("inbox", self.id("FOMC statement"))["view"]["endpoints"]
        self.assertEqual((endpoints["base"], endpoints["after_1"], endpoints["after_5"]),
                         ("2026-09-15", "2026-09-17", "2026-09-23"))
        changes = {(change["short_label"], change["horizon"]): change for change in endpoints["changes"]}
        self.assertEqual(changes[("2-year", 1)]["change_bp"], "-4")
        self.assertEqual(changes[("2-year", 5)]["change_bp"], "+12")
        self.assertEqual(changes[("10-year", 1)]["change_bp"], "-2.5")
        self.assertEqual(changes[("10-year", 5)]["change_bp"], "0")
        self.assertEqual((changes[("2-year", 5)]["from_raw"], changes[("2-year", 5)]["to_raw"]), ("3.94", "4.06"))
        self.assertIn("basis points", endpoints["rule"]["statement"])
        self.assertIn("not a bond return", endpoints["rule"]["statement"])

    def test_the_rule_skips_holidays_and_the_context_day_itself(self):
        # Context date Friday 4 September 2026: the session before is 3 September; Monday 7 September is Labor Day.
        capture_id = capture(self.intake, "Jobs", "https://www.bls.gov/news.release/archives/empsit_09042026.htm",
                             "2026-09-04T08:30:00-04:00", NOW)
        work = market_retrieval.plan_view([f"capture-{capture_id}"], self.store, None, self.inbox, self.intake, None,
                                          self.clock)
        market_retrieval.dispatch(json.dumps({"plan_sha256": work["plan_sha256"], "events": [f"capture-{capture_id}"],
                                              "attempt": 1}).encode(), self.store, None, self.inbox, self.intake,
                                  self.board.fetcher(), self.clock)
        endpoints = self.page("capture", capture_id)["view"]["endpoints"]
        self.assertEqual((endpoints["base"], endpoints["after_1"], endpoints["after_5"]),
                         ("2026-09-03", "2026-09-08", "2026-09-14"))

    def test_missing_endpoints_stay_unavailable_and_no_other_date_is_used(self):
        self.confirm("FOMC statement", "2026-09-16")
        overrides = {date(2026, 9, 15): ("ND", "4.10"), date(2026, 9, 17): None}
        self.fetch("FOMC statement", board=FakeRelease(self.clock, overrides=overrides))
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        changes = {(change["short_label"], change["horizon"]): change for change in view["endpoints"]["changes"]}
        self.assertEqual(view["endpoints"]["base"], "2026-09-15")
        self.assertIsNone(changes[("2-year", 5)]["change_bp"])
        self.assertIn("the start session (2026-09-15): the source gives no value (ND)", changes[("2-year", 5)]["unavailable"])
        self.assertIn("the end session (2026-09-17): the source has no row", changes[("10-year", 1)]["unavailable"])
        self.assertIsNotNone(changes[("10-year", 5)]["change_bp"])
        self.assertEqual(self.day(view, "2026-09-15")["observations"]["RIFLGFCY02_N.B"]["status"], "session_missing")
        self.assertEqual(self.day(view, "2026-09-17")["observations"]["RIFLGFCY10_N.B"]["status"], "session_absent")
        self.assertIsNone(self.day(view, "2026-09-17")["observations"]["RIFLGFCY10_N.B"]["value"])

    def test_a_recent_event_has_a_partial_window_with_future_and_unreturned_dates(self):
        self.confirm("Jobs report", "2026-10-02")
        overrides = {date(2026, 10, 8): None}  # The package stops at 7 October.
        self.fetch("Jobs report", board=FakeRelease(self.clock, overrides=overrides))
        view = self.page("inbox", self.id("Jobs report"))["view"]
        status = {row["date"]: row["observations"]["RIFLGFCY02_N.B"]["status"] for row in view["days"]}
        self.assertEqual(status["2026-10-07"], "session_value")
        self.assertEqual(status["2026-10-08"], "after_retrieval")  # Before the request, after the last date held.
        self.assertEqual(status["2026-10-09"], "future")  # Today in New York.
        self.assertEqual(status["2026-10-10"], "weekend")
        self.assertEqual(status["2026-10-12"], "calendar_holiday")  # Columbus Day: no session, not a future gap.
        self.assertEqual(status["2026-10-13"], "future")
        self.assertFalse(view["complete"])
        changes = {(change["short_label"], change["horizon"]): change for change in view["endpoints"]["changes"]}
        self.assertEqual(view["endpoints"]["after_5"], "2026-10-09")
        self.assertIsNotNone(changes[("2-year", 1)]["change_bp"])
        self.assertIn("today or later", changes[("2-year", 5)]["unavailable"])
        plan = self.page("inbox", self.id("Jobs report"))["plan"]
        self.assertEqual(plan["missing_sessions"], ["2026-10-08"])
        self.assertEqual(plan["future_sessions"], ["2026-10-09", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"])

    def test_dates_no_retrieval_covers_are_not_held(self):
        self.confirm("FOMC statement", "2026-09-16")
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        self.assertEqual(self.day(view, "2026-09-15")["observations"]["RIFLGFCY02_N.B"]["status"], "not_held")
        self.assertTrue(all(change["change_bp"] is None for change in view["endpoints"]["changes"]))
        self.assertEqual(view["retrievals"], [])

    def test_retrieval_versions_that_disagree_are_kept_apart_and_never_combined(self):
        self.confirm("FOMC statement", "2026-09-16")
        first = self.put_retrieval(date(2026, 9, 2), date(2026, 9, 30), NOW - timedelta(days=5))
        second = self.put_retrieval(date(2026, 9, 14), date(2026, 9, 18), NOW - timedelta(days=1),
                                    {date(2026, 9, 15): ("3.99", synthetic_pair(date(2026, 9, 15))[1])})
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        conflicted = self.day(view, "2026-09-15")["observations"]["RIFLGFCY02_N.B"]
        self.assertEqual((conflicted["status"], conflicted["value"]), ("conflict", None))
        self.assertEqual(view["conflicts"], [{"date": "2026-09-15", "series": "RIFLGFCY02_N.B", "versions": [
            {"raw": synthetic_pair(date(2026, 9, 15))[0], "retrievals": [f"private:{first}"]},
            {"raw": "3.99", "retrievals": [f"private:{second}"]}]}])
        agreed = self.day(view, "2026-09-16")["observations"]["RIFLGFCY02_N.B"]
        self.assertEqual((agreed["status"], agreed["retrievals"]), ("session_value", sorted([f"private:{first}",
                                                                                             f"private:{second}"])))
        changes = {(change["short_label"], change["horizon"]): change for change in view["endpoints"]["changes"]}
        self.assertIn("retrieval versions disagree", changes[("2-year", 1)]["unavailable"])
        self.assertIsNotNone(changes[("10-year", 1)]["change_bp"])
        self.assertEqual(sorted(path.name for path in (self.store / "retrievals").iterdir()), sorted([first, second]))
        self.assertEqual({item["id"] for item in view["retrievals"]}, {f"private:{first}", f"private:{second}"})

    def test_a_corrupted_retrieval_is_reported_left_unchanged_and_not_used(self):
        self.confirm("FOMC statement", "2026-09-16")
        self.put_retrieval(date(2026, 9, 2), date(2026, 9, 30), NOW - timedelta(days=1))
        folder = next((self.store / "retrievals").iterdir())
        writable(folder / "source.csv")
        (folder / "source.csv").write_bytes((folder / "source.csv").read_bytes().replace(b"2026-09-15,", b"2026-09-15,9"))
        before = fingerprint(self.store)
        page = self.page("inbox", self.id("FOMC statement"))
        self.assertEqual([problem["retrieval"] for problem in page["store_problems"]], [f"private:{folder.name}"])
        self.assertIn("size and SHA-256", page["store_problems"][0]["problem"])
        self.assertEqual(self.day(page["view"], "2026-09-15")["observations"]["RIFLGFCY02_N.B"]["status"], "not_held")
        self.assertEqual(page["plan"]["requests"], 1)  # A new request would add a new retrieval beside it.
        self.assertEqual(fingerprint(self.store), before)

    def test_a_package_dated_after_the_day_it_was_requested_is_kept_but_not_accepted(self):
        self.confirm("FOMC statement", "2026-09-16")
        def late(request: httpx.Request) -> httpx.Response:  # Observations through 12 October, requested on 9 October.
            return package_reply(release_zip(release_data(date(2026, 9, 1), date(2026, 10, 12))), NOW)

        result = self.fetch("FOMC statement", board=FakeRelease(self.clock, script=[late]))
        self.assertEqual((result["outcome"], result["validation"]), ("retained_not_accepted", "refused"))
        self.assertIn("after the day the package was requested (2026-10-09)", result["detail"])
        page = self.page("inbox", self.id("FOMC statement"))
        self.assertEqual(self.day(page["view"], "2026-09-15")["observations"]["RIFLGFCY02_N.B"]["status"], "not_held")
        self.assertEqual([package["status"] for package in page["packages_not_used"]], ["refused"])
        self.assertFalse((self.store / "retrievals").exists())


class BundleReuseTests(Folders):
    def test_committed_downloads_are_reused_in_place_with_their_provenance(self):
        before = fingerprint(market_context.BUNDLE_DIR)
        self.confirm("June statement", "2025-06-18")
        page = self.page("inbox", self.id("June statement"), market_context.BUNDLE_DIR)
        view = page["view"]
        self.assertTrue(view["complete"])
        self.assertEqual(page["plan"]["requests"], 0)
        self.assertEqual(view["conflicts"], [])
        self.assertTrue(all(item["origin"] == "bundle" for item in view["retrievals"]))
        self.assertIn("bundle:run-2:fomc-2025-06-18", {item["id"] for item in view["retrievals"]})
        rows = market_context.parse_h15_csv((market_context.BUNDLE_DIR / "sources" / "fomc-2025-06-18.csv").read_bytes())
        source = {day.isoformat(): raw for day, raw, _ in rows["RIFLGFCY02_N.B"]}
        for change in view["endpoints"]["changes"]:
            if change["series"] == "RIFLGFCY02_N.B":
                self.assertEqual((change["from_raw"], change["to_raw"]), (source[change["from"]], source[change["to"]]))
        self.assertEqual(view["endpoints"]["after_1"], "2025-06-20")  # 19 June 2025 was a SIFMA holiday.
        self.assertEqual(fingerprint(market_context.BUNDLE_DIR), before)
        self.assertFalse((self.store / "retrievals").exists())  # Nothing was copied.

    def test_a_bundle_download_that_does_not_verify_is_not_used_and_the_rest_still_are(self):
        bundle = self.root / "bundle"
        shutil.copytree(market_context.BUNDLE_DIR, bundle)
        csv = bundle / "sources" / "fomc-2025-06-18.csv"
        csv.write_bytes(csv.read_bytes() + b"\r\n")
        found, problems = market_store.retrievals(self.store, bundle)
        self.assertEqual(len(found), 11)
        self.assertEqual([problem["retrieval"] for problem in problems], ["bundle:run-2:fomc-2025-06-18"])

    def test_reads_write_nothing_and_take_no_lock(self):
        self.confirm("FOMC statement", "2026-09-16")
        self.fetch("FOMC statement")
        before, beside = fingerprint(self.root), sorted(path.name for path in self.root.iterdir())
        self.page("inbox", self.id("FOMC statement"), market_context.BUNDLE_DIR)
        market_retrieval.listing(self.store, market_context.BUNDLE_DIR, self.inbox, self.intake, None, self.clock)
        market_retrieval.plan_view([self.key("FOMC statement")], self.store, None, self.inbox, self.intake, None,
                                   self.clock)
        self.assertEqual((fingerprint(self.root), sorted(path.name for path in self.root.iterdir())), (before, beside))


if __name__ == "__main__":
    unittest.main()

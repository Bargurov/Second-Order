"""Market-data retrievals for selected events: what a plan requests, and proof by request counts that nothing else is
requested. The Board's server is a SYNTHETIC in-process fake (tests/market_fakes.py) that serves release packages of
invented values and counts every request it receives; every folder is temporary and nothing reaches a network.
"""
from datetime import date, timedelta
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from market_fakes import SYNTHETIC_LABEL, FakeRelease, capture, keep_package, package_reply, release_data, release_zip
from second_order import market_context, market_package, market_retrieval, market_store
from second_order.api import create_app
from second_order.market_context import ContextRefused
from second_order.market_retrieval import FetchFailed, ReleaseFetcher
from second_order.store import canonical
from test_event_market_context import NOW, Folders, fingerprint

BASE = "http://127.0.0.1:8131"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Context": "1"}


class Retrievals(Folders):
    def plan(self, *keys: str) -> dict:
        return market_retrieval.plan_view(list(keys), self.store, None, self.inbox, self.intake, None, self.clock)

    def approve(self, plan: dict, board: FakeRelease | None = None, attempt: int | None = None,
                fetcher: ReleaseFetcher | None = None) -> dict:
        body = json.dumps({"plan_sha256": plan["plan_sha256"], "events": [event["key"] for event in plan["events"]],
                           "attempt": attempt or plan["next_attempt"]}).encode()
        return market_retrieval.dispatch(body, self.store, None, self.inbox, self.intake,
                                         fetcher or (board or self.board).fetcher(), self.clock)

    def refused(self, plan: dict, status: int = 409, **options) -> str:
        with self.assertRaises(ContextRefused) as refused:
            self.approve(plan, **options)
        self.assertEqual(refused.exception.status, status)
        return str(refused.exception)

    def kept(self) -> list[str]:
        folder = self.store / "packages"
        return sorted(path.name for path in folder.iterdir() if path.name.startswith("p")) if folder.is_dir() else []

    def staging_left(self) -> list[str]:
        folder = self.store / "packages"
        return [path.name for path in folder.iterdir() if path.name.startswith(".staging")] if folder.is_dir() else []


class CallCountTests(Retrievals):
    def test_all_cached_work_sends_nothing(self):
        self.confirm("FOMC statement", "2026-09-16")
        self.assertEqual(self.approve(self.plan(self.key("FOMC statement")))["outcome"], "saved")
        cached = self.plan(self.key("FOMC statement"))
        self.assertEqual((cached["requests"], cached["request"], cached["missing_sessions"]), (0, None, []))
        self.assertEqual(cached["held_sessions"], 20)
        self.assertIn("Nothing is missing", self.refused(cached))
        self.assertEqual(len(self.board.calls), 1)

    def test_the_plan_discloses_the_full_release_package_and_one_request_fetches_it(self):
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        request = plan["request"]
        self.assertEqual((plan["plan_version"], plan["requests"], request["url"], request["download"]),
                         ("market-retrieval-plan-0.2", 1, market_package.PACKAGE_URL, "full_release_package"))
        self.assertEqual((request["missing_sessions"], request["missing_from"], request["missing_to"]),
                         (20, "2026-09-02", "2026-09-30"))
        self.assertEqual(plan["source"]["id"], "board-h15-release-xml")
        for words in ("every series of the release", "over its full history", "not limited to the two series or to the "
                      "missing dates", "kept privately so that later selections reuse it"):
            self.assertIn(words, plan["source"]["download"])
        self.assertNotIn("from=", request["url"])  # Neither date-bounded nor a two-series download.
        result = self.approve(plan)
        self.assertEqual((result["result_version"], result["outcome"], result["validation"]),
                         ("market-retrieval-result-0.2", "saved", "accepted"))
        self.assertEqual(self.board.calls, [market_package.PACKAGE_URL])
        sent = self.board.headers[0]
        self.assertEqual((sent["accept"], sent["accept-encoding"], sent["user-agent"]),
                         ("*/*", "identity", market_retrieval.USER_AGENT))
        self.assertNotIn("cookie", sent)

    def test_one_kept_package_covers_later_selections_without_another_request(self):
        self.confirm("FOMC statement", "2026-09-16")
        self.approve(self.plan(self.key("FOMC statement")))
        july = capture(self.intake, "Statement", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
                       "2026-07-29T14:00:00-04:00", NOW)
        self.confirm("CPI report", "2026-09-11")
        self.confirm("Jobs report", "2026-10-02")
        keys = [f"capture-{july}", self.key("CPI report"), self.key("Jobs report")]
        for key in keys:
            self.assertEqual(self.plan(key)["requests"], 0, key)
        combined = self.plan(*keys)
        self.assertEqual((combined["requests"], combined["missing_sessions"]), (0, []))
        self.assertEqual({item["retrieval"] for item in combined["reuse"]}, {f"package:{self.kept()[0]}"})
        self.assertTrue(self.page("capture", july)["view"]["complete"])
        self.assertTrue(self.page("inbox", self.id("CPI report"))["view"]["complete"])
        self.assertEqual(len(self.board.calls), 1)

    def test_sessions_after_a_kept_package_need_a_new_approval_and_the_packages_agree(self):
        self.confirm("Jobs report", "2026-10-02")
        self.approve(self.plan(self.key("Jobs report")))
        self.clock.advance(days=10)  # 19 October: 9 to 16 October have now passed, and no package holds them.
        later = self.plan(self.key("Jobs report"))
        self.assertEqual((later["requests"], later["request"]["missing_from"], later["request"]["missing_to"]),
                         (1, "2026-10-09", "2026-10-16"))
        self.approve(later)
        view = self.page("inbox", self.id("Jobs report"))["view"]
        self.assertTrue(view["complete"])
        self.assertEqual(view["conflicts"], [])
        self.assertEqual(len({item["id"] for item in view["retrievals"]}), 2)
        self.assertEqual((len(self.board.calls), len(self.kept())), (2, 2))

    def test_concurrent_approvals_of_the_same_work_send_one_request(self):
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        board = FakeRelease(self.clock, before=lambda request: time.sleep(0.3))
        start, outcomes = threading.Barrier(3), []

        def approve():
            start.wait()
            try:
                outcomes.append(self.approve(plan, board)["outcome"])
            except market_store.StoreRefused as exc:
                outcomes.append(exc.status)
            except ContextRefused as exc:
                outcomes.append(exc.status)

        workers = [threading.Thread(target=approve) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sorted(outcomes, key=str), [409, 409, "saved"])
        self.assertEqual(len(board.calls), 1)
        self.assertEqual(len(self.kept()), 1)

    def test_a_repeated_approval_after_success_sends_nothing(self):
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        self.approve(plan)
        self.assertIn("changed since the preview", self.refused(plan))
        self.assertIn("changed since the preview", self.refused(plan, attempt=2))
        self.assertEqual(len(self.board.calls), 1)

    def test_the_plan_is_checked_again_immediately_before_sending(self):
        self.confirm("FOMC statement", "2026-09-16")
        self.confirm("Late statement", "2026-09-16")
        stale = self.plan(self.key("FOMC statement"))
        self.approve(self.plan(self.key("Late statement")))  # Another tab fetched the same window meanwhile.
        self.assertIn("changed since the preview", self.refused(stale))
        self.assertEqual(len(self.board.calls), 1)

    def test_the_attempt_is_recorded_before_the_request_is_sent(self):
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        seen = []

        def before(request):
            seen.append((market_store.started_path(self.store, plan["plan_sha256"], 1).is_file(),
                         market_store.outcome_path(self.store, plan["plan_sha256"], 1).exists()))

        self.approve(plan, FakeRelease(self.clock, before=before))
        self.assertEqual(seen, [(True, False)])
        started = json.loads(market_store.started_path(self.store, plan["plan_sha256"], 1).read_text(encoding="utf-8"))
        self.assertEqual((started["attempt_version"], started["url"], started["download"], started["events"],
                          started["client"]["transport"]),
                         ("market-retrieval-attempt-0.2", market_package.PACKAGE_URL, "full_release_package",
                          [self.key("FOMC statement")], SYNTHETIC_LABEL))

    def test_an_approval_of_an_earlier_plan_version_cannot_authorize_this_source(self):
        self.confirm("FOMC statement", "2026-09-16")
        current = self.plan(self.key("FOMC statement"))
        earlier = {"plan_version": "market-retrieval-plan-0.1", "source": market_store.SOURCE_ID,
                   "events": [{"key": self.key("FOMC statement"), "context_date": "2026-09-16"}],
                   "missing": current["missing_sessions"],
                   "url": market_context.export_url(date(2026, 9, 2), date(2026, 9, 30))}
        old = {**current, "plan_sha256": hashlib.sha256(canonical(earlier).encode("utf-8")).hexdigest(), "next_attempt": 1}
        self.assertIn("changed since the preview", self.refused(old))
        self.assertEqual((self.board.calls, self.kept()), ([], []))
        self.assertFalse((self.store / "attempts" / old["plan_sha256"]).exists())


class FailureTests(Retrievals):
    def test_a_failed_attempt_stays_visible_and_is_never_retried(self):
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        board = FakeRelease(self.clock, script=["html"])
        result = self.approve(plan, board)
        self.assertEqual((result["outcome"], result["retries"], result["package_id"]), ("refused_reply", 0, None))
        self.assertIn("web page", result["detail"])
        self.assertEqual((len(board.calls), self.kept(), self.staging_left()), (1, [], []))
        self.assertIn("already started", self.refused(plan, board=board))
        again = self.plan(self.key("FOMC statement"))
        self.assertEqual((again["plan_sha256"], again["next_attempt"]), (plan["plan_sha256"], 2))
        page = self.page("inbox", self.id("FOMC statement"))
        self.assertEqual([(item["number"], item["outcome"]["outcome"]) for item in page["attempts"]],
                         [(1, "refused_reply")])
        self.assertEqual(len(board.calls), 1)
        self.assertEqual(self.approve(again, board)["outcome"], "saved")  # A new attempt, explicitly approved.
        self.assertEqual(len(board.calls), 2)

    def test_timeouts_and_error_statuses_are_recorded_with_a_bounded_untrusted_excerpt(self):
        self.confirm("FOMC statement", "2026-09-16")
        board = FakeRelease(self.clock, script=["timeout", 503])
        first = self.approve(self.plan(self.key("FOMC statement")), board)
        self.assertEqual(first["outcome"], "no_reply")
        self.assertIn("whether it received the request is not known", first["detail"])
        second = self.approve(self.plan(self.key("FOMC statement")), board)
        self.assertEqual(second["outcome"], "refused_reply")
        attempts = market_store.read_attempts(self.store)
        self.assertEqual([(item["number"], item["outcome"]["http_status"]) for item in attempts], [(1, None), (2, 503)])
        excerpt = attempts[1]["outcome"]["error_excerpt"]
        self.assertEqual((excerpt["untrusted"], excerpt["bytes"], excerpt["complete"]), (True, 4096, False))
        self.assertTrue(excerpt["text"].startswith("<html>unavailable</html>"))
        self.assertEqual((len(board.calls), self.kept()), (2, []))

    def test_a_content_encoding_is_refused_and_never_decoded(self):
        self.confirm("FOMC statement", "2026-09-16")
        result = self.approve(self.plan(self.key("FOMC statement")), FakeRelease(self.clock, script=["gzip"]))
        self.assertEqual(result["outcome"], "refused_reply")
        self.assertIn("gzip-encoded although identity was requested; it was not read or decoded", result["detail"])
        self.assertEqual((self.kept(), self.staging_left()), ([], []))

    def test_unsafe_or_corrupt_archives_are_not_kept(self):
        self.confirm("FOMC statement", "2026-09-16")
        good = release_zip(release_data(date(2026, 9, 1), date(2026, 10, 8)))
        replies = {
            "unsafe_archive": release_zip(release_data(date(2026, 9, 1), date(2026, 10, 8)), {"../outside.xml": b"x"}),
            "archive_limit": release_zip(release_data(date(2026, 9, 1), date(2026, 10, 8)),
                                         {"padding.xml": b"\0" * (8 * 1024 * 1024)}),
            "malformed_archive": good[:len(good) // 2],
        }
        for kind, data in replies.items():
            with self.subTest(kind=kind):
                board = FakeRelease(self.clock, script=[lambda request, data=data: package_reply(data, NOW)])
                result = self.approve(self.plan(self.key("FOMC statement")), board)
                self.assertEqual(result["outcome"], "refused_reply")
                self.assertIn("The reply was not kept", result["detail"])
                self.assertIn(f"({kind})", result["detail"])
                self.assertEqual((self.kept(), self.staging_left()), ([], []))

    def test_a_package_whose_data_is_not_accepted_is_kept_listed_and_never_used(self):
        self.confirm("FOMC statement", "2026-09-16")
        data = release_data(date(2026, 9, 1), date(2026, 10, 8)).replace(
            b"?>\r\n", b'?>\r\n<!DOCTYPE message:MessageGroup [<!ENTITY note "x">]>\r\n', 1)
        board = FakeRelease(self.clock, script=[lambda request: package_reply(release_zip(data), NOW)])
        result = self.approve(self.plan(self.key("FOMC statement")), board)
        self.assertEqual((result["outcome"], result["validation"]), ("retained_not_accepted", "refused"))
        self.assertIn("H15_data.xml has a DOCTYPE declaration, which the parser policy refuses", result["detail"])
        self.assertEqual(self.kept(), [result["package_id"]])
        page = self.page("inbox", self.id("FOMC statement"))
        self.assertEqual(self.day(page["view"], "2026-09-15")["observations"]["RIFLGFCY02_N.B"]["status"], "not_held")
        self.assertEqual(page["plan"]["requests"], 1)
        self.assertEqual([(item["package_id"], item["status"]) for item in page["packages_not_used"]],
                         [(result["package_id"], "refused")])
        listing = market_retrieval.listing(self.store, None, self.inbox, self.intake, None, self.clock)
        self.assertEqual([item["status"] for item in listing["packages"]], ["refused"])
        self.assertEqual(listing["retrievals"], [])

    def test_no_cookie_is_sent_and_no_set_cookie_value_is_kept(self):
        self.confirm("Jobs report", "2026-10-02")
        self.approve(self.plan(self.key("Jobs report")))
        self.clock.advance(days=10)
        self.approve(self.plan(self.key("Jobs report")))  # The first reply set cookies; a new request sends none.
        self.assertEqual(len(self.board.headers), 2)
        self.assertTrue(all("cookie" not in headers for headers in self.board.headers))
        for path in self.store.rglob("*.json"):
            self.assertNotIn("SYNTHETIC-COOKIE-VALUE", path.read_text(encoding="utf-8"), path.name)
        record = json.loads((self.store / "packages" / self.kept()[0] / "acquisition.json").read_text(encoding="utf-8"))
        self.assertEqual(record["set_cookie"], {"present": True, "count": 2, "values_stored": False})
        self.assertNotIn("set-cookie", record["response_headers"])
        self.assertEqual(record["headers"]["content-encoding"], None)  # A missing header stays null.

    def test_a_server_without_market_retrieval_sends_nothing(self):
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        self.assertFalse(plan["retrieval"]["enabled"])
        self.assertIn("--enable-market-retrieval", plan["retrieval"]["detail"])
        body = json.dumps({"plan_sha256": plan["plan_sha256"], "events": [self.key("FOMC statement")], "attempt": 1})
        with self.assertRaises(ContextRefused) as refused:
            market_retrieval.dispatch(body.encode(), self.store, None, self.inbox, self.intake, None, self.clock)
        self.assertEqual(refused.exception.status, 409)
        self.assertFalse((self.store / "attempts").exists())

    def test_requests_are_bounded_and_go_only_to_the_board(self):
        self.confirm("FOMC statement", "2026-09-16")
        for url in ("https://example.com/FRB_h15_xml.zip", market_package.PACKAGE_URL + "?x=1",
                    market_context.export_url(date(2026, 9, 2), date(2026, 9, 30))):
            with self.subTest(url=url), self.assertRaises(FetchFailed):
                self.board.fetcher().fetch(url, self.root / "never.zip")
        self.assertEqual(self.board.calls, [])
        data = release_zip(release_data(date(2026, 9, 1), date(2026, 10, 8)))
        declared = lambda request: package_reply(data, NOW, {"content-length": str(market_package.MAX_TRANSFER + 1)})
        streamed = lambda request: package_reply(data, NOW, {"content-length": None})
        short = lambda request: package_reply(data, NOW, {"content-length": str(len(data) + 10)})
        moved = lambda request: httpx.Response(302, headers={"location": "https://elsewhere.example/"})
        typed = lambda request: package_reply(data, NOW, {"content-type": "application/octet-stream"})
        cases = ((declared, f"declares {market_package.MAX_TRANSFER + 1} bytes"), (streamed, "exceeded 1000 bytes"),
                 (short, f"declared {len(data) + 10} bytes and {len(data)} arrived"),
                 (moved, "redirects are not followed"), (typed, "application/octet-stream, not the ZIP package"))
        for script, words in cases:
            with self.subTest(words=words), patch.object(market_package, "MAX_TRANSFER",
                                                         1000 if script is streamed else market_package.MAX_TRANSFER):
                result = self.approve(self.plan(self.key("FOMC statement")), FakeRelease(self.clock, script=[script]))
                self.assertEqual(result["outcome"], "refused_reply")
                self.assertIn(words, result["detail"])
        self.assertEqual((self.kept(), self.staging_left()), ([], []))

    def test_a_reply_that_trickles_past_the_deadline_is_refused_and_the_timeouts_are_bounded(self):
        self.assertEqual(market_retrieval.TIMEOUT, httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0))
        self.assertEqual(market_retrieval.DEADLINE_SECONDS, 600)
        self.assertEqual((market_package.MAX_TRANSFER, market_package.MAX_ENTRIES, market_package.MAX_ENTRY,
                          market_package.MAX_TOTAL, market_package.MAX_RATIO),
                         (200 * 1024 * 1024, 50, 512 * 1024 * 1024, 1024 * 1024 * 1024, 200))
        self.confirm("FOMC statement", "2026-09-16")

        class Slow(httpx.SyncByteStream):
            def __iter__(self):
                yield b"PK"
                time.sleep(0.3)
                yield b"rest"

        slow = lambda request: httpx.Response(200, stream=Slow(), headers={"content-type": "application/zip"})
        with patch.object(market_retrieval, "DEADLINE_SECONDS", 0.1):
            result = self.approve(self.plan(self.key("FOMC statement")), FakeRelease(self.clock, script=[slow]))
        self.assertEqual(result["outcome"], "refused_reply")
        self.assertIn("took longer than 0.1 seconds", result["detail"])
        self.assertEqual((self.kept(), self.staging_left()), ([], []))

    def test_only_confirmed_supported_events_can_be_planned(self):
        with self.assertRaises(ContextRefused) as unconfirmed:
            self.plan(self.key("FOMC statement"))
        self.assertEqual(unconfirmed.exception.status, 409)
        with self.assertRaises(ContextRefused) as outside:
            self.plan(self.key("Energy article"))
        self.assertEqual(outside.exception.status, 422)
        for keys in ([], ["inbox-nowhere-x"], [self.key("FOMC statement")] * 2):
            with self.subTest(keys=keys), self.assertRaises(ContextRefused):
                self.plan(*keys)


class LocalValidationTests(Retrievals):
    """A package kept outside the app (an operator's one-off acquisition) is used only after local validation."""

    def keep(self, start=date(2026, 1, 2), end=date(2026, 10, 8), requested=NOW - timedelta(hours=20)) -> str:
        return keep_package(self.store, release_zip(release_data(start, end)), requested)

    def test_a_kept_package_is_not_used_until_validated_and_validation_fetches_nothing(self):
        package_id = self.keep()
        self.confirm("FOMC statement", "2026-09-16")
        plan = self.plan(self.key("FOMC statement"))
        self.assertEqual(plan["requests"], 1)  # Not validated: not used, so a request would still be needed...
        self.assertEqual([(item["package_id"], item["status"]) for item in plan["packages_not_used"]],
                         [(package_id, "acquired_unvalidated")])  # ...and the plan says a package is held.
        blocked = AssertionError("validation tried to open a network connection")
        with patch("socket.create_connection", side_effect=blocked), patch("socket.getaddrinfo", side_effect=blocked):
            results = market_retrieval.validate_packages(self.store, self.clock)
        self.assertEqual([(item["package"], item["result"]) for item in results], [(package_id, "accepted")])
        after = self.plan(self.key("FOMC statement"))
        self.assertEqual((after["requests"], after["packages_not_used"]), (0, []))
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        self.assertTrue(view["complete"])
        self.assertEqual([item["id"] for item in view["retrievals"]], [f"package:{package_id}"])
        before = fingerprint(self.store)
        self.assertEqual([item["result"] for item in market_retrieval.validate_packages(self.store, self.clock)],
                         ["already_accepted"])
        self.assertEqual(fingerprint(self.store), before)
        self.assertEqual(self.board.calls, [])

    def test_reads_never_validate_a_package(self):
        package_id = self.keep()
        self.confirm("FOMC statement", "2026-09-16")
        before = fingerprint(self.store)
        self.page("inbox", self.id("FOMC statement"))
        market_retrieval.listing(self.store, None, self.inbox, self.intake, None, self.clock)
        self.plan(self.key("FOMC statement"))
        self.assertEqual(fingerprint(self.store), before)
        self.assertEqual(sorted(path.name for path in (self.store / "packages" / package_id).iterdir()),
                         ["acquisition.json", "package.zip"])


class StoreWriteTests(Retrievals):
    def test_records_are_created_once_complete_and_read_only(self):
        path = self.store / "attempts" / ("a" * 64) / "1.started.json"
        market_store.write_exclusive(path, {"number": 1})
        with self.assertRaises(FileExistsError):
            market_store.write_exclusive(path, {"number": 2})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"number": 1})
        self.assertEqual([item.name for item in path.parent.iterdir()], ["1.started.json"])  # No temporary file left.
        with self.assertRaises(PermissionError):
            path.write_text("replaced", encoding="utf-8")


class ApiTests(Retrievals):
    def app(self, board: FakeRelease | None = None):
        return create_app(self.root / "prepared", None, intake=self.intake, inbox=self.inbox, market=self.store,
                          context=self.root / "no-bundle", market_fetcher=(board or self.board).fetcher(),
                          market_clock=self.clock)

    def test_reopening_and_restarting_send_nothing(self):
        item = self.id("FOMC statement")
        with TestClient(self.app(), base_url=BASE) as client:
            reads = ("/api/market-context", f"/api/market-context/inbox/{item}",
                     f"/api/market-context/plan?event={self.key('Jobs report')}")
            self.assertEqual(client.get(reads[1]).status_code, 200)
            body = {"context_date": "2026-09-16", "convention": "new-york-calendar-date-1", "version": 1}
            self.assertEqual(client.post(f"/api/market-context/inbox/{item}/confirm", json=body,
                                         headers=HEADERS).status_code, 201)
            self.assertEqual(client.post(f"/api/market-context/inbox/{item}/confirm", json=body,
                                         headers=HEADERS).status_code, 200)  # A repeated click writes nothing.
            page = client.get(reads[1]).json()
            self.assertEqual((page["plan"]["requests"], len(self.board.calls)), (1, 0))
            approval = {"plan_sha256": page["plan"]["plan_sha256"], "events": [page["event"]["key"]], "attempt": 1}
            result = client.post("/api/market-context/retrievals", json=approval, headers=HEADERS)
            self.assertEqual((result.status_code, result.json()["outcome"]), (201, "saved"))
            self.assertEqual(client.post("/api/market-context/retrievals", json=approval, headers=HEADERS).status_code,
                             409)
            for _ in range(3):
                for path in reads[:2]:
                    self.assertEqual(client.get(path).status_code, 200)
            self.assertEqual(client.get(reads[2]).status_code, 409)  # Not confirmed: refused, nothing requested.
            reopened = client.get(reads[1]).json()
            listed = client.get(reads[0]).json()
        self.assertEqual(len(self.board.calls), 1)
        self.assertEqual([item["status"] for item in listed["packages"]], ["accepted"])
        restarted = FakeRelease(self.clock)
        with TestClient(self.app(restarted), base_url=BASE) as client:
            self.assertEqual(client.get(reads[1]).json(), reopened)
            self.assertEqual(client.get(reads[0]).status_code, 200)
        self.assertEqual(restarted.calls, [])

    def test_writes_need_this_server_s_own_page(self):
        item = self.id("FOMC statement")
        body = {"context_date": "2026-09-16", "convention": "new-york-calendar-date-1", "version": 1}
        with TestClient(self.app(), base_url=BASE) as client:
            for headers, status in (({**HEADERS, "Origin": "http://evil.example"}, 403),
                                    ({key: value for key, value in HEADERS.items() if key != "X-Second-Order-Context"}, 403),
                                    ({**HEADERS, "Content-Type": "text/plain"}, 415)):
                for path in (f"/api/market-context/inbox/{item}/confirm", "/api/market-context/retrievals"):
                    with self.subTest(path=path, headers=headers):
                        self.assertEqual(client.post(path, content=json.dumps(body), headers=headers).status_code,
                                         status)
            self.assertEqual(client.get("/api/market-context", headers={"host": "evil.example"}).status_code, 403)
            self.assertEqual(client.post("/api/market-context/retrievals", json={"plan_sha256": "x"},
                                         headers=HEADERS).status_code, 422)
            self.assertEqual(client.get("/api/market-context/elsewhere/x").status_code, 404)
        self.assertFalse(self.store.exists())
        self.assertEqual(self.board.calls, [])


if __name__ == "__main__":
    unittest.main()

"""Credits, daily limits, quotes and reservations (docs/admin-user-contract.md, sections 7 and 8).

SYNTHETIC accounts and terms in temporary stores. The admin sets every number and nothing has a built-in value; a quote
binds user, request, Effort, policy and expiry; a reservation rechecks everything in one transaction, so concurrent
threads and separate processes never exceed a daily limit or spend credits that are not there; every resolution
happens once and never charges more than was reserved; the ledger is append-only and reconciles; restarts keep
everything; and quota days follow the configured time zone across daylight-saving changes.
"""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from account_fakes import POLICY, START, World
from second_order import accounts as acc, entitlements as ent
from second_order.accounts import AccountsRefused

REQUEST = "20261014T090000000000Z-0123456789ab.research-prompt-1.high"
SHA = "a" * 64


class Entitlements(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.accounts, self.ids = self.world.accounts, self.world.ids
        self.admin, self.user = self.ids["admin"], self.ids["reader-a"]

    def refused(self, code: str, action) -> AccountsRefused:
        with self.assertRaises(AccountsRefused) as caught:
            action()
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def terms(self, credits: int = 40, limit: int = 3, user: str = "reader-a") -> None:
        if ent.current_policy(self.accounts) is None:
            ent.add_policy(self.accounts, POLICY, self.admin, "synthetic", START)
        ent.add_credits(self.accounts, self.ids[user], "grant", credits, self.admin, "synthetic", f"grant-{user}-01",
                        START)
        ent.set_daily_limit(self.accounts, self.ids[user], limit, self.admin, "synthetic", START)

    def quote(self, request_id: str = REQUEST, effort: str = "high", user: str = "reader-a",
              moment: datetime = START, input_tokens: int = 4_500) -> dict:
        return ent.issue_quote(self.accounts, user_id=self.ids[user], request_id=request_id, request_sha256=SHA,
                               effort=effort, model="claude-sonnet-5-5", input_tokens_assumed=input_tokens,
                               max_tokens=16_000, planning_estimate_usd=0.2, moment=moment)

    def reserve(self, quote: dict, user: str = "reader-a", moment: datetime = START, **changes) -> tuple[dict, bool]:
        values = {"user_id": self.ids[user], "quote_id": quote["quote_id"], "request_id": quote["request_id"],
                  "request_sha256": SHA, "model": "claude-sonnet-5-5", "effort": quote["effort"],
                  "credits": quote["credits"], "moment": moment} | changes
        return ent.reserve(self.accounts, **values)

    # ---------------------------------------------------------------- policy

    def test_nothing_is_quoted_without_an_admin_policy_and_nothing_runs_without_a_daily_limit(self):
        self.refused("no_credit_policy", self.quote)
        ent.add_policy(self.accounts, POLICY, self.admin, "synthetic", START)
        quote = self.quote()
        ent.add_credits(self.accounts, self.user, "grant", 40, self.admin, "synthetic", "grant-key-0001", START)
        self.refused("no_daily_limit", lambda: self.reserve(quote))
        self.assertEqual(ent.balance(self.accounts, self.user)["available"], 40)

    def test_a_policy_enables_only_verified_levels_with_whole_number_rates(self):
        bad = [{**POLICY, "model": "claude-other"}, {**POLICY, "efforts": {"ultra": {"extra_credits": 0}}},
               {**POLICY, "efforts": {"low": {"extra_credits": -1}}},
               {**POLICY, "efforts": {"low": {"extra_credits": 0, "max_tokens": 9}}},
               {**POLICY, "credits": {**POLICY["credits"], "base": 0}},
               {**POLICY, "credits": {**POLICY["credits"], "per_1k_input_tokens": 1.5}},
               {**POLICY, "max_request_usd": 0}, {**POLICY, "quote_valid_seconds": 5},
               {key: value for key, value in POLICY.items() if key != "credits"}, {**POLICY, "settlement": "usage"}]
        for body in bad:
            self.refused("invalid_request", lambda: ent.add_policy(self.accounts, body, self.admin, "x", START))
        first = ent.add_policy(self.accounts, POLICY, self.admin, "first", START)
        second = ent.add_policy(self.accounts, {**POLICY, "efforts": {"max": {"extra_credits": 3}}}, self.admin,
                                "second", START)
        self.assertEqual((first["policy_version"], second["policy_version"]), ("credit-policy-1", "credit-policy-2"))
        self.assertEqual(ent.offered_efforts(second, "claude-sonnet-5-5"), ["max"])
        self.assertEqual(len(ent.policies(self.accounts)), 2)
        self.assertEqual(second["settlement"], "quoted")

    def test_credits_follow_request_size_effort_and_the_output_bound(self):
        ent.add_policy(self.accounts, POLICY, self.admin, "synthetic", START)
        small, large = self.quote(input_tokens=1_200), self.quote(request_id=REQUEST[:-4] + "low", effort="low",
                                                                  input_tokens=9_100)
        self.assertEqual(small["credits"], 1 + 2 * 1 + 0 + 2)   # base + ceil(1.2k) input + output 0/1k + high extra
        self.assertEqual(large["credits"], 1 + 10 * 1 + 0 + 0)
        self.assertNotEqual(self.quote(input_tokens=1_200)["credits"], self.quote(input_tokens=8_000)["credits"])
        self.assertEqual(datetime.fromisoformat(small["expires_at"]) - START, timedelta(seconds=900))
        over = ent.issue_quote
        self.refused("request_over_budget", lambda: over(
            self.accounts, user_id=self.user, request_id=REQUEST, request_sha256=SHA, effort="high",
            model="claude-sonnet-5-5", input_tokens_assumed=10, max_tokens=16_000, planning_estimate_usd=5.01,
            moment=START))
        error = self.refused("unsupported_effort", lambda: self.quote(effort="max"))
        self.assertEqual(error.extra["efforts"], ["low", "medium", "high"])

    # ---------------------------------------------------------------- reservations

    def test_a_reservation_rechecks_the_quote_and_refuses_tampering_expiry_and_policy_changes(self):
        self.terms()
        quote = self.quote()
        for changes in ({"effort": "low"}, {"credits": quote["credits"] - 1}, {"request_sha256": "b" * 64},
                        {"request_id": REQUEST[:-4] + "low"}, {"quote_id": "q-unknown"}, {"quote_id": None}):
            self.refused("quote_mismatch", lambda: self.reserve(quote, **changes))
        self.terms(user="reader-b")
        self.refused("quote_mismatch", lambda: self.reserve(quote, user="reader-b"))
        self.refused("quote_expired", lambda: self.reserve(quote, moment=START + timedelta(seconds=900)))
        ent.add_policy(self.accounts, POLICY, self.admin, "a new version", START)
        self.refused("quote_superseded", lambda: self.reserve(quote))
        self.assertEqual(ent.attempts(self.accounts), [])
        self.assertEqual(ent.balance(self.accounts, self.user)["available"], 40)

    def test_credits_and_the_daily_limit_are_enforced_and_reported(self):
        self.terms(credits=10, limit=1)
        first, duplicate = self.reserve(self.quote())
        self.assertFalse(duplicate)
        self.assertEqual(ent.balance(self.accounts, self.user)["available"], 10 - first["credits"])
        second = self.quote(request_id=REQUEST[:-4] + "low", effort="low")
        error = self.refused("daily_limit_reached", lambda: self.reserve(second))
        self.assertEqual(error.extra["resets_at"], "2026-10-14T21:00:00+00:00")
        self.assertEqual(error.extra["daily"]["remaining"], 0)
        ent.set_daily_limit(self.accounts, self.user, 5, self.admin, "raise", START)
        error = self.refused("insufficient_credits", lambda: self.reserve(second))
        self.assertEqual(error.extra["credits"]["available"], 10 - first["credits"])

    def test_a_repeated_approval_returns_its_attempt_and_changes_nothing(self):
        self.terms()
        quote, other = self.quote(), self.quote()  # Two quotes for one analysis, both issued before it ran.
        made, _ = self.reserve(quote)
        again, duplicate = self.reserve(quote, moment=START + timedelta(hours=2))  # Even after the quote expired.
        self.assertTrue(duplicate)
        self.assertEqual(again, made)
        self.assertEqual(len(ent.ledger(self.accounts, self.user)), 2)  # The grant and one hold.
        self.refused("already_attempted", lambda: self.reserve(other))
        self.refused("already_attempted", self.quote)  # No new quote for an analysis that ran.

    # ---------------------------------------------------------------- resolutions and the ledger

    def test_each_attempt_resolves_once_and_never_charges_more_than_it_reserved(self):
        self.terms()
        made, _ = self.reserve(self.quote())
        attempt = made["attempt_id"]
        self.refused("invalid_request", lambda: ent.resolve(self.accounts, attempt, "charged", made["credits"] + 1,
                                                            self.admin, "x", START))
        first, created = ent.resolve(self.accounts, attempt, "charged", 3, self.admin, "partial", START)
        second, again = ent.resolve(self.accounts, attempt, "returned", 0, self.admin, "late", START)
        self.assertEqual((created, again, second), (True, False, first))
        balance = ent.balance(self.accounts, self.user)
        self.assertEqual((balance["available"], balance["held"], balance["charged"]), (37, 0, 3))
        self.assertTrue(balance["reconciles"])
        with self.accounts.writing() as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO resolutions VALUES (?, 'returned', 0, 1, 'x', 'x', 'x')", (attempt,))

    def test_an_attempt_the_store_shows_as_sent_is_never_returned_automatically(self):
        self.terms()
        made, _ = self.reserve(self.quote())
        self.assertTrue(ent.mark_sent(self.accounts, made["attempt_id"], START))
        self.refused("invalid_request", lambda: ent.resolve(self.accounts, made["attempt_id"], "returned", 0,
                                                            ent.SYSTEM, "x", START, unsent_only=True))
        later = START + timedelta(days=3)  # A new calendar day releases nothing.
        self.assertEqual(ent.user_snapshot(self.accounts, self.user, later)["credits"]["held"], made["credits"])

    def test_a_returned_attempt_cannot_be_sent_and_frees_its_daily_slot(self):
        self.terms(limit=1)
        made, _ = self.reserve(self.quote())
        ent.resolve(self.accounts, made["attempt_id"], "returned", 0, ent.SYSTEM, "nothing was sent", START,
                    unsent_only=True)
        self.assertFalse(ent.mark_sent(self.accounts, made["attempt_id"], START))
        snapshot = ent.user_snapshot(self.accounts, self.user, START)
        self.assertEqual((snapshot["daily"]["used"], snapshot["credits"]), (0, {"available": 40, "held": 0}))

    def test_grants_are_idempotent_corrections_never_go_negative_and_the_ledger_is_append_only(self):
        first, created = ent.add_credits(self.accounts, self.user, "grant", 5, self.admin, "x", "key-00000001", START)
        again, repeated = ent.add_credits(self.accounts, self.user, "grant", 5, self.admin, "x", "key-00000001", START)
        self.assertEqual((created, repeated, again["entry_id"]), (True, False, first["entry_id"]))
        self.refused("invalid_request", lambda: ent.add_credits(self.accounts, self.user, "grant", 6, self.admin, "x",
                                                                "key-00000001", START))
        self.refused("invalid_request", lambda: ent.add_credits(self.accounts, self.user, "correction", -6,
                                                                self.admin, "x", "key-00000002", START))
        for bad in (0, -1, True, 1.5):
            self.refused("invalid_request", lambda: ent.add_credits(self.accounts, self.user, "grant", bad,
                                                                    self.admin, "x", "key-00000003", START))
        ent.add_credits(self.accounts, self.user, "correction", -2, self.admin, "typo", "key-00000004", START)
        self.assertEqual(ent.balance(self.accounts, self.user)["available"], 3)
        self.refused("not_found", lambda: ent.add_credits(self.accounts, self.admin, "grant", 5, self.admin, "x",
                                                          "key-00000005", START))
        self.terms()  # Rows in every append-only table, so each trigger has something to protect.
        made, _ = self.reserve(self.quote())
        ent.mark_sent(self.accounts, made["attempt_id"], START)
        ent.resolve(self.accounts, made["attempt_id"], "charged", 1, self.admin, "x", START)
        acc.assign(self.accounts, "capture", "20261014T090000000000Z-0123456789ab", self.user, self.admin, "x", START)
        for statement in ("UPDATE ledger SET amount = 100", "DELETE FROM ledger", "UPDATE attempts SET credits = 1",
                          "DELETE FROM resolutions", "UPDATE daily_limits SET daily_limit = 9",
                          "DELETE FROM credit_policies", "UPDATE record_owners SET user_id = 'x'",
                          "DELETE FROM quotes", "UPDATE attempt_sends SET sent_at = 'x'", "DELETE FROM attempts"):
            with self.accounts.writing() as connection, self.assertRaises(sqlite3.IntegrityError, msg=statement):
                connection.execute(statement)

    def test_the_ledger_reconciles_grants_corrections_charges_returns_and_holds(self):
        self.terms(credits=50, limit=10)
        held, _ = self.reserve(self.quote(request_id=REQUEST[:-4] + "low", effort="low"))
        charged, _ = self.reserve(self.quote())
        returned, _ = self.reserve(self.quote(request_id=REQUEST[:-4] + "medium", effort="medium"))
        ent.resolve(self.accounts, charged["attempt_id"], "charged", charged["credits"], ent.SYSTEM, "x", START)
        ent.resolve(self.accounts, returned["attempt_id"], "returned", 0, ent.SYSTEM, "x", START)
        ent.add_credits(self.accounts, self.user, "correction", -3, self.admin, "x", "key-correction", START)
        balance = ent.balance(self.accounts, self.user)
        self.assertTrue(balance["reconciles"])
        self.assertEqual(balance["held"], held["credits"])
        self.assertEqual(balance["available"], 50 - 3 - charged["credits"] - held["credits"])

    # ---------------------------------------------------------------- concurrency and restarts

    def race(self, count: int, action) -> list:
        barrier, results = threading.Barrier(count), []

        def worker(index):
            barrier.wait()
            try:
                results.append(("ok", action(index)))
            except AccountsRefused as exc:
                results.append(("refused", exc.code))
        threads = [threading.Thread(target=worker, args=(index,)) for index in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        return results

    def test_concurrent_reservations_at_the_daily_boundary_allow_exactly_the_limit(self):
        self.terms(credits=1_000, limit=2)
        quotes = [self.quote(request_id=f"20261014T09000000000{index}Z-0123456789ab.research-prompt-1.high")
                  for index in range(8)]
        results = self.race(8, lambda index: self.reserve(quotes[index]))
        self.assertEqual(sum(1 for state, _ in results if state == "ok"), 2)
        self.assertEqual(sorted(code for state, code in results if state == "refused"), ["daily_limit_reached"] * 6)
        self.assertEqual(ent.user_snapshot(self.accounts, self.user, START)["daily"]["used"], 2)

    def test_concurrent_reservations_at_the_credit_boundary_never_overspend(self):
        quote_credits = 8  # base 1 + 5 (4.5k input) + high 2
        self.terms(credits=3 * quote_credits + 2, limit=100)
        quotes = [self.quote(request_id=f"20261014T09000000000{index}Z-0123456789ab.research-prompt-1.high")
                  for index in range(7)]
        self.assertEqual({quote["credits"] for quote in quotes}, {quote_credits})
        results = self.race(7, lambda index: self.reserve(quotes[index]))
        self.assertEqual(sum(1 for state, _ in results if state == "ok"), 3)
        balance = ent.balance(self.accounts, self.user)
        self.assertEqual(balance["available"], 2)
        self.assertGreaterEqual(balance["available"], 0)
        self.assertTrue(balance["reconciles"])

    def test_concurrent_duplicate_approvals_reserve_once(self):
        self.terms()
        quote = self.quote()
        results = self.race(6, lambda index: self.reserve(quote))
        made = {result[1][0]["attempt_id"] for result in results}
        self.assertEqual(len(made), 1)
        self.assertEqual(sum(1 for _, (attempt, duplicate) in results if not duplicate), 1)
        self.assertEqual(len([row for row in ent.ledger(self.accounts, self.user) if row["kind"] == "hold"]), 1)

    def test_separate_processes_share_one_limit_and_one_balance(self):
        self.terms(credits=1_000, limit=3)
        quotes = [self.quote(request_id=f"20261014T09000000000{index}Z-0123456789ab.research-prompt-1.high")
                  for index in range(6)]
        script = ("import json, sys\nfrom datetime import datetime\nfrom pathlib import Path\n"
                  "from second_order import accounts as acc, entitlements as ent\n"
                  "store = acc.Accounts.open(Path(sys.argv[1])); quote = json.loads(sys.argv[2])\n"
                  "try:\n"
                  "    ent.reserve(store, user_id=quote['user_id'], quote_id=quote['quote_id'], "
                  "request_id=quote['request_id'], request_sha256=quote['request_sha256'], model='claude-sonnet-5-5', "
                  "effort=quote['effort'], credits=quote['credits'], moment=datetime.fromisoformat(sys.argv[3]))\n"
                  "    print('ok')\n"
                  "except acc.AccountsRefused as exc:\n    print(exc.code)\n")
        root = Path(__file__).resolve().parent.parent
        processes = [subprocess.Popen([sys.executable, "-c", script, str(self.world.store_path), json.dumps(quote),
                                       START.isoformat()], cwd=root, stdout=subprocess.PIPE, text=True)
                     for quote in quotes]
        outputs = sorted(process.communicate(timeout=120)[0].strip() for process in processes)
        self.assertEqual(outputs, ["daily_limit_reached"] * 3 + ["ok"] * 3)
        self.assertEqual(ent.user_snapshot(self.accounts, self.user, START)["daily"]["used"], 3)

    def test_a_restart_keeps_balances_counters_quotes_and_attempts(self):
        self.terms()
        quote = self.quote()
        made, _ = self.reserve(quote)
        reopened = acc.Accounts.open(self.world.store_path)  # A new server process over the same file.
        self.assertEqual(ent.balance(reopened, self.user), ent.balance(self.accounts, self.user))
        self.assertEqual(ent.user_snapshot(reopened, self.user, START)["daily"]["used"], 1)
        again, duplicate = ent.reserve(reopened, user_id=self.user, quote_id=quote["quote_id"], request_id=REQUEST,
                                       request_sha256=SHA, model="claude-sonnet-5-5", effort="high",
                                       credits=quote["credits"], moment=START)
        self.assertEqual((again["attempt_id"], duplicate), (made["attempt_id"], True))

    # ---------------------------------------------------------------- quota days

    def test_quota_days_follow_jerusalem_across_both_2026_daylight_saving_changes(self):
        zone = "Asia/Jerusalem"
        # Daylight time ends on Sunday 25 October 2026 at 02:00 IDT: that day lasts 25 hours.
        start, end = ent.day_start(date(2026, 10, 25), zone), ent.day_start(date(2026, 10, 26), zone)
        self.assertEqual((start.isoformat(), end - start), ("2026-10-24T21:00:00+00:00", timedelta(hours=25)))
        # It began on Friday 27 March 2026 at 02:00 IST: that day lasts 23 hours.
        start, end = ent.day_start(date(2026, 3, 27), zone), ent.day_start(date(2026, 3, 28), zone)
        self.assertEqual((start.isoformat(), end - start), ("2026-03-26T22:00:00+00:00", timedelta(hours=23)))
        moments = {"2026-10-24T20:59:59+00:00": "2026-10-24", "2026-10-24T21:00:00+00:00": "2026-10-25",
                   "2026-10-25T21:59:59+00:00": "2026-10-25", "2026-10-25T22:00:00+00:00": "2026-10-26",
                   "2026-10-14T20:59:59+00:00": "2026-10-14", "2026-10-14T21:00:00+00:00": "2026-10-15"}
        for moment, day in moments.items():
            self.assertEqual(ent.quota_day(datetime.fromisoformat(moment), zone), day, moment)
        self.assertEqual(ent.next_reset(datetime.fromisoformat("2026-10-25T01:30:00+00:00"), zone).isoformat(),
                         "2026-10-25T22:00:00+00:00")
        # A zone whose transition skips midnight: the day starts at the transition, and days stay contiguous.
        skipped = ent.day_start(date(2026, 9, 6), "America/Santiago")
        self.assertEqual(skipped.astimezone(timezone.utc).isoformat(), "2026-09-06T04:00:00+00:00")
        self.assertEqual(ent.day_start(date(2026, 9, 7), "America/Santiago") - skipped, timedelta(hours=23))

    def test_an_attempt_keeps_its_quota_day_and_the_limit_resets_at_local_midnight(self):
        self.terms(credits=100, limit=1)
        late = datetime(2026, 10, 14, 20, 50, tzinfo=timezone.utc)  # 23:50 in Jerusalem.
        made, _ = self.reserve(self.quote(moment=late), moment=late)
        self.assertEqual(made["quota_day"], "2026-10-14")
        after = datetime(2026, 10, 14, 21, 5, tzinfo=timezone.utc)  # 00:05 on the 15th in Jerusalem.
        next_quote = self.quote(request_id=REQUEST[:-4] + "low", effort="low", moment=after)
        made_next, _ = self.reserve(next_quote, moment=after)
        self.assertEqual(made_next["quota_day"], "2026-10-15")
        snapshot = ent.user_snapshot(self.accounts, self.user, after)
        self.assertEqual((snapshot["daily"]["day"], snapshot["daily"]["used"]), ("2026-10-15", 1))

    def test_the_quota_time_zone_is_a_recorded_admin_setting(self):
        self.assertEqual(acc.quota_timezone(self.accounts), "Asia/Jerusalem")
        self.refused("invalid_request", lambda: acc.set_quota_timezone(self.accounts, "Mars/Olympus", self.admin, "x"))
        acc.set_quota_timezone(self.accounts, "UTC", self.admin, "synthetic change", START)
        self.assertEqual(acc.quota_timezone(self.accounts), "UTC")
        self.assertEqual([row["value"] for row in acc.settings_history(self.accounts)], ["UTC"])
        self.terms(limit=5)
        made, _ = self.reserve(self.quote(moment=START), moment=START)
        self.assertEqual((made["quota_day"], made["quota_timezone"]), ("2026-10-14", "UTC"))


if __name__ == "__main__":
    unittest.main()

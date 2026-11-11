"""One credit-policy (and usage-policy) publication per explicit intent (QA-5), on the real application with SYNTHETIC accounts.

Each submission of the Admin form carries an idempotency key, bound in the accounts store to the administrator who used
it and to the canonical payload (policy and reason). Repeating it (a double click, a lost reply submitted again, two
requests at once) publishes nothing more and answers with the version it published; the same key with other values or
from another administrator is refused and writes nothing; a new intent sends a new key and publishes a new version.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from account_fakes import ADMIN_WRITE, POLICY, USAGE_POLICY, World
from second_order import accounts as acc, entitlements as ent, usage


class PolicyPublication(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.admin = self.world.client("admin")
        self.addCleanup(self.admin.close)

    def publish(self, client, key: str, policy: dict | None = None, reason: str = "SYNTHETIC policy"):
        return client.post("/api/admin/policy", headers=ADMIN_WRITE,
                           json={"policy": policy or POLICY, "reason": reason, "idempotency_key": key})

    def rows(self, table: str) -> list[tuple]:
        connection = sqlite3.connect(self.world.store_path)
        try:
            return connection.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            connection.close()

    def test_a_repeated_submission_publishes_once_and_answers_with_its_version(self):
        first = self.publish(self.admin, "policy-intent-0001")
        self.assertEqual((first.status_code, first.json()["created"]), (201, True))
        again = self.publish(self.admin, "policy-intent-0001")  # A double click, or a lost reply submitted again.
        self.assertEqual((again.status_code, again.json()["created"]), (200, False))
        self.assertEqual(again.json()["published"], first.json()["published"])
        self.assertEqual(len(ent.policies(self.world.accounts)), 1)
        self.assertEqual(len(self.rows("publications")), 1)

    def test_concurrent_repeats_of_one_submission_publish_one_version(self):
        start = threading.Barrier(6)

        def submit(_):
            with self.world.client("admin") as client:
                start.wait(10)
                return self.publish(client, "policy-intent-race").status_code
        with ThreadPoolExecutor(6) as pool:
            statuses = sorted(pool.map(submit, range(6)))
        self.assertEqual(statuses, [200] * 5 + [201])
        self.assertEqual(len(ent.policies(self.world.accounts)), 1)

    def test_a_key_reused_for_other_values_or_by_another_administrator_is_refused_and_writes_nothing(self):
        self.assertEqual(self.publish(self.admin, "policy-intent-0002").status_code, 201)
        before = (self.rows("credit_policies"), self.rows("publications"))
        other_values = self.publish(self.admin, "policy-intent-0002", POLICY | {"quote_valid_seconds": 600})
        other_reason = self.publish(self.admin, "policy-intent-0002", reason="SYNTHETIC: another reason")
        acc.create_user(self.world.accounts, "admin-two", "Second admin (synthetic)", "admin",
                        "synthetic-admin-two-pass", "test-setup", self.world.clock())
        with self.world.client() as second:
            signed = second.post("/api/session/login", headers={**ADMIN_WRITE, "X-Second-Order-Session": "1"},
                                 json={"username": "admin-two", "password": "synthetic-admin-two-pass"})
            second.headers["X-Second-Order-Account"] = signed.json()["user"]["user_id"]
            other_admin = self.publish(second, "policy-intent-0002")
        for reply in (other_values, other_reason, other_admin):
            self.assertEqual((reply.status_code, reply.json()["code"]), (409, "idempotency_conflict"), reply.text)
        self.assertEqual((self.rows("credit_policies"), self.rows("publications")), before)

    def test_each_deliberate_intent_publishes_a_new_version_and_a_key_is_required(self):
        self.assertEqual(self.publish(self.admin, "policy-intent-0003").status_code, 201)
        self.assertEqual(self.publish(self.admin, "policy-intent-0004").status_code, 201)  # The same values, again.
        self.assertEqual([row["policy_version"] for row in ent.policies(self.world.accounts)],
                         ["credit-policy-1", "credit-policy-2"])
        for form in ({"policy": POLICY, "reason": "SYNTHETIC"},
                     {"policy": POLICY, "reason": "SYNTHETIC", "idempotency_key": "short"},
                     {"policy": POLICY, "reason": "SYNTHETIC", "idempotency_key": "ключ-ключ-ключ"}):
            reply = self.admin.post("/api/admin/policy", headers=ADMIN_WRITE, json=form)
            self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_request"), form)
        self.assertEqual(len(ent.policies(self.world.accounts)), 2)

    def test_usage_limits_are_published_once_per_intent_and_key_as_well(self):
        """The usage policy (docs/news-usage-contract.md, section 2) follows the same rules: concurrent repeats publish
        one version, another administrator's use of the key is refused and writes nothing."""
        def publish(client, key: str):
            return client.post("/api/admin/usage-policy", headers=ADMIN_WRITE, json={
                "policy": USAGE_POLICY, "reason": "SYNTHETIC usage limits", "idempotency_key": key})
        start = threading.Barrier(6)

        def submit(_):
            with self.world.client("admin") as client:
                start.wait(10)
                return publish(client, "usage-intent-race").status_code
        with ThreadPoolExecutor(6) as pool:
            self.assertEqual(sorted(pool.map(submit, range(6))), [200] * 5 + [201])
        before = (self.rows("usage_policies"), self.rows("publications"))
        acc.create_user(self.world.accounts, "admin-two", "Second admin (synthetic)", "admin",
                        "synthetic-admin-two-pass", "test-setup", self.world.clock())
        with self.world.client() as second:
            signed = second.post("/api/session/login", headers={**ADMIN_WRITE, "X-Second-Order-Session": "1"},
                                 json={"username": "admin-two", "password": "synthetic-admin-two-pass"})
            second.headers["X-Second-Order-Account"] = signed.json()["user"]["user_id"]
            other_admin = publish(second, "usage-intent-race")
        self.assertEqual((other_admin.status_code, other_admin.json()["code"]), (409, "idempotency_conflict"))
        self.assertEqual((self.rows("usage_policies"), self.rows("publications")), before)
        self.assertEqual([row["policy_version"] for row in usage.policies(self.world.accounts)], ["usage-policy-1"])


if __name__ == "__main__":
    unittest.main()

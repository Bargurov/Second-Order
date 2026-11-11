"""Headline triage, summary and classification quality: the 25-word summary and the 30-word relation reason are brevity
targets, not acceptance boundaries; the taxonomy separates analysis and forecasts from formal statistical releases; and a response rejected under
an earlier validation policy can be re-checked locally, on request, without touching its records or calling anything.

SYNTHETIC feeds through an injected MockTransport and a fake provider that counts every request, in temporary folders.
These tests prove the software's behaviour only: they cannot show that the revised prompt yields better real output.
Nothing here reaches a network, reads a real key or touches data/.
"""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from test_event_inbox import BASE, Network, fingerprint
from test_headline_triage import (CORRECTION, NOTE, PREPARED_AT, STATEMENT, TRIAGE_HEADERS, Provider, Triage, entry_ids,
                                  reply, results)
from test_triage_scope import legacy_record
from second_order import event_inbox, headline_triage
from second_order.api import create_app
from second_order.headline_triage import (CATEGORIES, SOURCE_KINDS, VALIDATION_POLICIES, VALIDATION_POLICY,
                                          ResponseRejected, build_request, canonical_pairs, parse_response, snapshot_item)
from second_order.triage_flow import (TriageRefused, dispatch, listing, load_record, read_attempt, request_view,
                                      requests_dir)
from second_order.triage_recheck import revalidate

# Grounded in the title alone ("Federal Reserve issues FOMC statement"): 26 words, one past the target, and no more.
GROUNDED_26 = ("The Federal Reserve issued an FOMC statement; only its headline was supplied, so the text does not say what "
               "the Committee decided or when it met.")
# Grounded in two titles dated the same day: 34 words, four past the 30-word target for a relation reason.
REASON_34 = ("Both are Federal Reserve items dated September 16, 2026 by link and feed timestamp; one is the FOMC statement "
             "and the other its implementation note, so they may concern the same single meeting decision.")
EARLIER_CATEGORIES = ("Policy decision", "Meeting minutes or record", "Data release", "Update or correction",
                      "Announcement or notice", "Other", "Insufficient information")


def with_summary(item_id: str, summary: str):
    """A fake reply: short results for every entry, and ``summary`` for one of them."""
    def respond(request: dict) -> tuple:
        found = results(entry_ids(request))
        for result in found:
            if result["id"] == item_id:
                result.update(category="Policy decision", event_type="FOMC statement", summary=summary)
        return reply(found)
    return respond


class PolicyTests(Triage):
    def setUp(self):
        super().setUp()
        self.entries = [snapshot_item(item) for item in self.items if item["title"] in (STATEMENT, NOTE)]
        self.ids = [entry["id"] for entry in self.entries]

    def parse(self, found: list[dict], relations: list | None = None, scope: list | None = None, policy=None) -> dict:
        return parse_response(reply(found, relations or [])[1], self.entries, [], scope=scope or [], policy=policy)

    def test_a_grounded_26_word_summary_is_not_rejected_for_length(self):
        self.assertEqual(len(GROUNDED_26.split()), 26)
        found = [dict(result, summary=GROUNDED_26) for result in results(self.ids)]
        parsed = self.parse(found)
        self.assertEqual((parsed["results"][self.ids[0]]["summary"], parsed["validation_policy"]),
                         (GROUNDED_26, "triage-validation-3"))
        with self.assertRaises(ResponseRejected) as caught:  # The earlier policy, kept for its records, did reject it.
            self.parse(found, policy="triage-validation-1")
        self.assertIn("longer than 25 words", str(caught.exception))

    def test_technical_limits_and_structural_rules_still_reject(self):
        limit = VALIDATION_POLICIES[VALIDATION_POLICY]["summary_words"]
        self.assertEqual(limit, 60)
        one = results(self.ids)
        accepted = self.parse([dict(one[0], summary=" ".join(["word"] * 60))] + one[1:])
        self.assertEqual(len(accepted["results"][self.ids[0]]["summary"].split()), 60)
        cases = {
            "past the technical limit": ([dict(one[0], summary=" ".join(["word"] * 61))] + one[1:], None,
                                         "longer than 60 words"),
            "too many characters": ([dict(one[0], summary="x" * 601)] + one[1:], None, "longer than 60 words"),
            "a missing result": (one[1:], None, "have no result"),
            "an unknown category": ([dict(one[0], category="Market moving")] + one[1:], None, "outside the taxonomy"),
            "an extra field": ([dict(one[0], importance="high")] + one[1:], None, "must contain exactly"),
            "an event type with insufficient information": (
                [dict(one[0], category="Insufficient information", event_type="FOMC statement")] + one[1:], None,
                "still names an event type"),
            "a relation outside the scope": (one, [{"relation": "separate_releases", "item_ids": self.ids,
                                                    "reason": "r"}], "planned no comparisons"),
        }
        for name, (found, relations, expected) in cases.items():
            with self.subTest(name), self.assertRaises(ResponseRejected) as caught:
                self.parse(found, relations)
            self.assertIn(expected, str(caught.exception))
        with self.assertRaises(ValueError):
            self.parse(one, policy="triage-validation-9")


class ReasonPolicyTests(Triage):
    """triage-validation-3: a relation reason has a 30-word target and a 60-word, 600-character technical limit."""

    def setUp(self):
        super().setUp()
        chosen = (self.id(STATEMENT, "0916a"), self.id(NOTE))  # The same day: one planned pair.
        self.entries = [snapshot_item(item) for item in self.items if item["id"] in chosen]
        self.ids = [entry["id"] for entry in self.entries]
        self.scope = canonical_pairs([self.ids])

    def parse(self, reason: str, scope: list | None = None, policy=None, members: list | None = None) -> dict:
        relation = {"relation": "possibly_same_event", "item_ids": members or self.ids, "reason": reason}
        body = reply(results(self.ids), [relation])[1]
        return parse_response(body, self.entries, [], scope=self.scope if scope is None else scope, policy=policy)

    def test_a_grounded_34_word_reason_passes_the_length_check(self):
        self.assertEqual(len(REASON_34.split()), 34)
        parsed = self.parse(REASON_34)
        self.assertEqual((parsed["relations"][0]["reason"], parsed["validation_policy"]), (REASON_34, "triage-validation-3"))
        for earlier in ("triage-validation-1", "triage-validation-2"):  # Kept as they were, for their records.
            with self.subTest(earlier), self.assertRaises(ResponseRejected) as caught:
                self.parse(REASON_34, policy=earlier)
            self.assertIn("reason of relation 1 is longer than 30 words", str(caught.exception))

    def test_excessive_text_stays_bounded_and_every_other_rule_still_applies(self):
        self.assertEqual(len(self.parse(" ".join(["word"] * 60))["relations"][0]["reason"].split()), 60)
        for reason in (" ".join(["word"] * 61), "x" * 601):
            with self.subTest(length=len(reason)), self.assertRaises(ResponseRejected) as caught:
                self.parse(reason)
            self.assertIn("reason of relation 1 is longer than 60 words", str(caught.exception))
        with self.assertRaises(ResponseRejected) as caught:  # Out of scope: no pair was planned.
            self.parse(REASON_34, scope=[])
        self.assertIn("planned no comparisons", str(caught.exception))
        with self.assertRaises(ResponseRejected) as caught:  # A supplied item outside the pair is still refused.
            self.parse(REASON_34, members=self.ids + [next(item["id"] for item in self.items if item["id"] not in self.ids)])
        self.assertTrue("not supplied" in str(caught.exception) or "did not plan" in str(caught.exception))
        found = [dict(result, event_type=" ".join(["w"] * 9)) for result in results(self.ids)]
        with self.assertRaises(ResponseRejected) as caught:  # Event types keep their hard 8-word limit.
            parse_response(reply(found)[1], self.entries, [], scope=self.scope)
        self.assertIn("longer than 8 words", str(caught.exception))


class PromptTests(Triage):
    def test_the_prompt_targets_grounded_brevity_and_names_each_sources_kind(self):
        request = build_request([], [], [])
        system = request["system"]
        for phrase in ("about 25 words", "never past 60", "do not pad", "nothing from memory",
                       "When only the title is supplied (excerpt null), keep the summary short",
                       "chosen by what the item is, not by its topic",
                       "A recurring release for another date or reporting period is another event",
                       "about 30 words naming what in the supplied text suggests it",
                       "(Prompt triage-prompt-5, schema triage-schema-4.)"):
            self.assertIn(phrase, system)
        self.assertEqual([key for key, _ in SOURCE_KINDS], list(event_inbox.SOURCES))  # One line per inbox source.
        for key, kind in SOURCE_KINDS:
            self.assertIn(f"{key}: {kind}", system)
            self.assertEqual("formal statistical releases" in kind,
                             event_inbox.SOURCES[key].kind == "Statistical release", key)

    def test_the_taxonomy_only_grows_so_earlier_results_stay_valid(self):
        self.assertTrue(set(EARLIER_CATEGORIES) <= set(CATEGORIES))
        self.assertEqual(set(CATEGORIES) - set(EARLIER_CATEGORIES), {"Forecast or projection", "Analysis or report"})
        self.assertIn("an article that analyzes or cites figures is not one", CATEGORIES["Data release"])
        schema = build_request([], [], [])["output_config"]["format"]["schema"]
        self.assertEqual(schema["properties"]["results"]["items"]["properties"]["category"]["enum"], list(CATEGORIES))


class Recheck(Triage):
    """A paid reply rejected under the earlier policy for a 26-word summary, as the real trial was."""

    def setUp(self):
        super().setUp()
        self.statement, self.note = self.id(STATEMENT, "0916a"), self.id(NOTE)
        self.provider = Provider(with_summary(self.statement, GROUNDED_26))
        self.view0 = self.prepare(self.statement, self.note, mode="paid")
        self.triage_id = self.view0["plan"]["triage_id"]
        plan = self.view0["plan"]
        body = json.dumps({"request_sha256": plan["request_sha256"], "approve_paid_request": True, "reprocess_ids": [],
                           "comparison_pairs": plan["pairs"]["needed"],
                           "estimated_max_usd": plan["cost_estimate"]["estimated_paid_if_output_reaches_max_usd"]})
        dispatch(self.triage_id, "paid", body.encode(), self.provider.senders(paid=True), self.triage,
                 lambda: PREPARED_AT, policy="triage-validation-1")
        self.attempt = requests_dir(self.triage) / self.triage_id / "paid"
        self.original = fingerprint(self.attempt)
        self.calls = len(self.provider.requests)

    def app(self):
        return create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                          self.root / "intake", self.root / "attempts", inbox=self.inbox, feeds=Network({}).fetcher(),
                          triage=self.triage, triage_senders=self.provider.senders(paid=True))

    def recheck(self, client: TestClient, name: str = "paid", sha: str | None = None):
        record = load_record(self.triage, self.triage_id)
        sha = sha or read_attempt(record, "paid")["response_sha256"]
        return client.post(f"/api/triage/{self.triage_id}/{name}/revalidate", headers=TRIAGE_HEADERS,
                           json={"response_sha256": sha})


class RecheckTests(Recheck):
    def test_the_earlier_rejection_stays_recorded_as_it_was(self):
        attempt = read_attempt(load_record(self.triage, self.triage_id), "paid")
        self.assertEqual((attempt["outcome"], attempt["validation_policy"], self.calls),
                         ("not_accepted", "triage-validation-1", 1))
        self.assertIn("longer than 25 words", attempt["message"])
        self.assertEqual(attempt["revalidation"], None)
        (row,) = listing(self.triage)["requests"]
        self.assertTrue(row["attempts"]["paid"]["revalidatable"])
        view = self.view(self.statement, self.note, mode="paid")
        self.assertEqual(({item["status"] for item in view["items"]}, view["plan"]["requests"]), ({"unresolved"}, 0))

    def test_a_local_recheck_accepts_it_apart_from_the_original_records_and_calls_nothing(self):
        before_root = fingerprint(self.root)
        blocked = AssertionError("a local re-check tried to open a network connection")
        with TestClient(self.app(), base_url=BASE) as client, patch("socket.create_connection", side_effect=blocked), \
                patch("socket.getaddrinfo", side_effect=blocked):
            first = self.recheck(client)
            again = self.recheck(client)
        self.assertEqual((first.status_code, again.status_code, first.json()["revalidated_now"],
                          again.json()["revalidated_now"]), (201, 200, True, False))
        self.assertEqual(len(self.provider.requests), self.calls)  # Nothing was sent.
        after = fingerprint(self.attempt)
        self.assertEqual({path: digest for path, digest in after.items() if not path.startswith("revalidations/")},
                         self.original)  # The original request, response and rejection are byte for byte the same.
        self.assertEqual(set(after) - set(self.original), {"revalidations/triage-validation-3.json"})
        self.assertEqual(set(fingerprint(self.root)) - set(before_root),
                         {f"headline-triage/requests/{self.triage_id}/paid/revalidations/triage-validation-3.json"})
        shown = first.json()["attempts"]["paid"]
        self.assertEqual((shown["outcome"], shown["validation_policy"], shown["revalidation"]["outcome"],
                          shown["revalidation"]["validation_policy"], shown["result_basis"], shown["revalidatable"]),
                         ("not_accepted", "triage-validation-1", "accepted", "triage-validation-3",
                          "accepted_on_local_recheck", False))
        saved = json.loads((self.attempt / "revalidations" / "triage-validation-3.json").read_bytes())
        self.assertEqual((saved["original"]["outcome"], saved["original"]["validation_policy"],
                          saved["original"]["config"]["prompt_version"]),
                         ("not_accepted", "triage-validation-1", "triage-prompt-5"))
        self.assertIn("nothing was regenerated, re-sent, repaired or human-reviewed", saved["provenance"])
        summary = {row["input"]["id"]: row for row in self.view(self.statement, self.note, mode="paid")["items"]}
        statement = summary[self.statement]
        self.assertEqual((statement["status"], statement["result"]["summary"]), ("reuse", GROUNDED_26))
        self.assertEqual((statement["provenance"]["validation_policy"], statement["provenance"]["revalidation"]
                          ["original_outcome"], statement["provenance"]["revalidation"]["original_validation_policy"]),
                         ("triage-validation-3", "not_accepted", "triage-validation-1"))

    def test_an_accepted_recheck_is_never_resent_and_reads_stay_local(self):
        with TestClient(self.app(), base_url=BASE) as client:
            self.recheck(client)
        before = fingerprint(self.root)
        plan = self.view0["plan"]
        body = json.dumps({"request_sha256": plan["request_sha256"], "approve_paid_request": True,
                           "reprocess_ids": [self.statement, self.note], "comparison_pairs": plan["pairs"]["needed"],
                           "estimated_max_usd": plan["cost_estimate"]["estimated_paid_if_output_reaches_max_usd"]})
        with self.assertRaises(TriageRefused) as caught:
            dispatch(self.triage_id, "paid", body.encode(), self.provider.senders(paid=True), self.triage)
        self.assertIn("local re-check", str(caught.exception))
        blocked = AssertionError("a read tried to open a network connection")
        for _ in range(2):  # Reopening, as after a restart: reads only.
            with TestClient(self.app(), base_url=BASE) as client, patch("socket.create_connection", side_effect=blocked), \
                    patch("socket.getaddrinfo", side_effect=blocked):
                for path, params in (("/api/triage", None), (f"/api/triage/{self.triage_id}", None),
                                     ("/api/triage/selection", {"mode": "paid", "ids": [self.statement, self.note]})):
                    self.assertEqual(client.get(path, params=params).status_code, 200, path)
        self.assertEqual((fingerprint(self.root), len(self.provider.requests)), (before, self.calls))

    def test_a_recheck_must_name_a_rejected_response_and_writes_nothing_otherwise(self):
        before = fingerprint(self.root)
        with TestClient(self.app(), base_url=BASE) as client:
            refused = [self.recheck(client, sha="0" * 64).status_code, self.recheck(client, name="paid-2").status_code,
                       self.recheck(client, name="simulated").status_code, self.recheck(client, name="free").status_code,
                       client.post(f"/api/triage/{self.triage_id}/paid/revalidate", headers=TRIAGE_HEADERS,
                                   json={"response_sha256": "x", "extra": 1}).status_code,
                       client.post(f"/api/triage/{self.triage_id}/paid/revalidate", json={"response_sha256": "x"}
                                   ).status_code]
        self.assertEqual(refused, [409, 404, 404, 404, 422, 403])
        self.assertEqual(fingerprint(self.root), before)
        legacy = legacy_record(self.triage, [snapshot_item(item) for item in self.items[:1]], [], approved=[],
                               relations=[])
        with self.assertRaises(TriageRefused) as caught:
            revalidate(legacy, "simulated", json.dumps({"response_sha256": "x"}).encode(), self.triage)
        self.assertIn("not re-checked", str(caught.exception))

    def test_a_structural_rejection_stays_rejected_on_recheck(self):
        provider = Provider(lambda request: reply(results(entry_ids(request))[1:]))  # One result missing.
        view = self.prepare(self.id(CORRECTION), mode="paid")
        self.approve(view, provider, mode="paid")
        record = load_record(self.triage, view["plan"]["triage_id"])
        sha = read_attempt(record, "paid")["response_sha256"]
        shown = revalidate(view["plan"]["triage_id"], "paid", json.dumps({"response_sha256": sha}).encode(), self.triage)
        paid = shown["attempts"]["paid"]
        self.assertEqual((paid["outcome"], paid["revalidation"]["outcome"], paid["result"], paid["result_basis"]),
                         ("not_accepted", "not_accepted", None, None))
        self.assertIn("have no result", paid["revalidation"]["message"])
        self.assertEqual(self.view(self.id(CORRECTION), mode="paid")["items"][0]["status"], "unresolved")


class PolicyBindingTests(Triage):
    def test_the_current_policy_is_read_when_called_not_bound_at_import(self):
        provider = Provider(with_summary(self.id(STATEMENT, "0916a"), GROUNDED_26))
        with patch.object(headline_triage, "VALIDATION_POLICY", "triage-validation-1"):
            view = self.prepare(self.id(STATEMENT, "0916a"))
            shown = self.approve(view, provider)["attempts"]["simulated"]
        self.assertEqual((shown["outcome"], shown["validation_policy"]), ("not_accepted", "triage-validation-1"))
        self.assertTrue(shown["revalidatable"])  # Under the restored current policy, a re-check is now possible.


class RecheckHistoryTests(Triage):
    """A reply rejected for a 34-word reason: re-checked under triage-validation-2, then under triage-validation-3."""

    def test_each_policy_records_its_own_outcome_and_earlier_records_stay(self):
        statement, note = self.id(STATEMENT, "0916a"), self.id(NOTE)

        def respond(request: dict) -> tuple:
            return reply(results(entry_ids(request)), [{"relation": "possibly_same_event", "item_ids": [statement, note],
                                                        "reason": REASON_34}])
        provider = Provider(respond)
        view = self.prepare(statement, note, mode="paid")
        plan = view["plan"]
        body = json.dumps({"request_sha256": plan["request_sha256"], "approve_paid_request": True, "reprocess_ids": [],
                           "comparison_pairs": plan["pairs"]["needed"],
                           "estimated_max_usd": plan["cost_estimate"]["estimated_paid_if_output_reaches_max_usd"]})
        dispatch(plan["triage_id"], "paid", body.encode(), provider.senders(paid=True), self.triage, lambda: PREPARED_AT,
                 policy="triage-validation-2")
        attempt = requests_dir(self.triage) / plan["triage_id"] / "paid"
        original, calls = fingerprint(attempt), len(provider.requests)
        sha = read_attempt(load_record(self.triage, plan["triage_id"]), "paid")["response_sha256"]
        named = json.dumps({"response_sha256": sha}).encode()
        blocked = AssertionError("a re-check or read tried to open a network connection")
        with patch("socket.create_connection", side_effect=blocked), patch("socket.getaddrinfo", side_effect=blocked):
            with patch.object(headline_triage, "VALIDATION_POLICY", "triage-validation-2"):
                under_two = revalidate(plan["triage_id"], "paid", named, self.triage)["attempts"]["paid"]
            v2_record = (attempt / "revalidations" / "triage-validation-2.json").read_bytes()
            under_three = revalidate(plan["triage_id"], "paid", named, self.triage)
            repeated = revalidate(plan["triage_id"], "paid", named, self.triage)
            reopened = self.view(statement, note, mode="paid")
        self.assertEqual((under_two["revalidation"]["outcome"], under_two["result_basis"]), ("not_accepted", None))
        self.assertIn("longer than 30 words", under_two["revalidation"]["message"])
        shown = under_three["attempts"]["paid"]
        self.assertEqual((under_three["revalidated_now"], repeated["revalidated_now"]), (True, False))
        self.assertEqual((shown["outcome"], shown["validation_policy"], shown["revalidation"]["outcome"],
                          shown["revalidation"]["validation_policy"], shown["result_basis"]),
                         ("not_accepted", "triage-validation-2", "accepted", "triage-validation-3",
                          "accepted_on_local_recheck"))
        self.assertEqual([(check["validation_policy"], check["outcome"]) for check in shown["revalidations"]],
                         [("triage-validation-2", "not_accepted"), ("triage-validation-3", "accepted")])
        after = fingerprint(attempt)
        self.assertEqual({path: digest for path, digest in after.items() if not path.startswith("revalidations/")},
                         original)
        self.assertEqual((attempt / "revalidations" / "triage-validation-2.json").read_bytes(), v2_record)
        self.assertEqual(len(provider.requests), calls)
        self.assertEqual([relation["reason"] for relation in reopened["relations"]], [REASON_34])
        self.assertTrue(all(row["provenance"]["revalidation"]["original_validation_policy"] == "triage-validation-2"
                            for row in reopened["items"]))


class VersionChangeTests(Recheck):
    def test_prompt_and_policy_changes_never_start_paid_work_on_their_own(self):
        with TestClient(self.app(), base_url=BASE) as client:
            self.recheck(client)
        before = fingerprint(self.root)
        with patch.object(headline_triage, "PROMPT_VERSION", "triage-prompt-test"):
            view = self.view(self.statement, self.note, mode="paid")
            self.assertEqual(({row["status"] for row in view["items"]}, view["plan"]["requests"]),
                             ({"earlier_version"}, 0))
            with TestClient(self.app(), base_url=BASE) as client:
                posted = client.post("/api/triage", headers=TRIAGE_HEADERS, json={
                    "item_ids": [self.statement, self.note], "mode": "paid", "reprocess_ids": []})
            self.assertEqual((posted.status_code, posted.json()["plan"]["requests"]), (200, 0))
            regenerate = self.view(self.statement, self.note, mode="paid", reprocess=[self.statement])
            self.assertEqual(regenerate["plan"]["entries"], [self.statement])  # Only by explicit decision, and planned.
        self.assertEqual((fingerprint(self.root), len(self.provider.requests)), (before, self.calls))

    def test_an_unchecked_rejection_is_planned_again_only_on_preview_and_never_sent(self):
        before_calls = len(self.provider.requests)
        with patch.object(headline_triage, "PROMPT_VERSION", "triage-prompt-test"):
            view = self.prepare(self.statement, self.note, mode="paid")
        self.assertEqual((view["plan"]["requests"], len(view["plan"]["entries"])), (1, 2))  # A plan, not a send.
        self.assertFalse((requests_dir(self.triage) / view["plan"]["triage_id"] / "paid").exists())
        self.assertEqual(len(self.provider.requests), before_calls)
        self.assertEqual(request_view(self.triage_id, self.triage)["attempts"]["paid"]["outcome"], "not_accepted")


if __name__ == "__main__":
    unittest.main()

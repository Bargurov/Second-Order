"""Headline triage, comparison scope: a request may relate only the comparison pairs its preview planned.

The scope is the missing comparison work a request was planned for: canonical pairs, saved in it and part of its bytes
and SHA-256. Approval repeats it, dispatch refuses anything else (and stale work) before reserving, a reply relating any
other two items is rejected whole, and only scoped pairs count as compared. Requests saved under headline-triage-0.2
(no scope) stay readable and are never sent.

SYNTHETIC feeds through an injected MockTransport and a fake provider that counts every request, in temporary folders.
Nothing here reaches a network, reads a real key or touches data/.
"""
from itertools import combinations
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from test_event_inbox import BASE, Network, fingerprint
from test_headline_triage import (CORRECTION, GENERIC, JOBS_SEPT, MINUTES, NOTE, PREPARED_AT, STATEMENT, Provider,
                                  Triage, entry_ids, payload_of, reply, results)
from second_order.analysis_flow import _json_bytes
from second_order.api import create_app
from second_order.headline_triage import (LEGACY_TRIAGE_VERSION, MODEL, TRIAGE_VERSION, ResponseRejected,
                                          build_request, canonical_pairs, config, cost_estimate, parse_response,
                                          payload_json, sha256, snapshot_item)
from second_order.store import canonical
from second_order.triage_flow import (LEGACY, TriageRefused, TriageSenders, dispatch, listing, load_record,
                                      read_attempt, request_view, requests_dir)


def relating(*members: str, kind: str = "separate_releases"):
    """A fake reply: a valid result for every entry and one otherwise valid relation over ``members``."""
    def respond(request: dict) -> tuple:
        return reply(results(entry_ids(request)), [{"relation": kind, "item_ids": list(members),
                                                    "reason": "Synthetic relation for a scope test."}])
    return respond


def scoped_reply(kind: str = "possibly_same_event"):
    """A fake reply relating, once, every item of the request's scope that is paired with all the others in it."""
    def respond(request: dict) -> tuple:
        pairs = payload_of(request)["comparison_pairs"]
        relations = [{"relation": kind, "item_ids": list(pair), "reason": "Synthetic, in scope."} for pair in pairs[:1]]
        return reply(results(entry_ids(request)), relations)
    return respond


class Scope(Triage):
    def setUp(self):
        super().setUp()
        self.statement, self.note, self.correction = self.id(STATEMENT, "0916a"), self.id(NOTE), self.id(CORRECTION)
        self.july, self.jobs, self.minutes = self.id(STATEMENT, "0729a"), self.id(JOBS_SEPT), self.id(MINUTES)

    def outcome(self, view: dict, mode: str = "simulated") -> dict:
        return read_attempt(load_record(self.triage, view["plan"]["triage_id"]), mode)

    def saved(self, view: dict, name: str) -> dict:
        return json.loads((requests_dir(self.triage) / view["plan"]["triage_id"] / name).read_bytes())


class ReproductionTests(Scope):
    """The gap, reproduced first: a reply relating items the preview never planned to compare was accepted."""

    def test_a_relation_across_publishers_is_not_accepted(self):
        view = self.prepare(self.statement, self.jobs)
        self.assertEqual(view["plan"]["pairs"]["needed"], [])  # Different publishers: never a planned comparison.
        self.approve(view, Provider(relating(self.statement, self.jobs)))
        self.assertEqual(self.outcome(view)["outcome"], "not_accepted")

    def test_a_relation_outside_the_window_is_not_accepted(self):
        view = self.prepare(self.statement, self.july)
        self.assertEqual(view["plan"]["pairs"]["needed"], [])  # 49 days apart.
        self.approve(view, Provider(relating(self.statement, self.july)))
        self.assertEqual(self.outcome(view)["outcome"], "not_accepted")

    def test_a_group_with_an_unplanned_pair_is_not_accepted(self):
        view = self.prepare(self.statement, self.correction, self.july)
        self.assertEqual(view["plan"]["pairs"]["needed"], canonical_pairs([[self.statement, self.correction]]))
        self.approve(view, Provider(relating(self.statement, self.correction, self.july, kind="possibly_same_event")))
        self.assertEqual(self.outcome(view)["outcome"], "not_accepted")


class SavedScopeTests(Scope):
    def test_the_scope_is_the_planned_missing_work_saved_in_the_request_and_its_identity(self):
        view = self.prepare(self.statement, self.note, self.correction, self.july, self.jobs)
        scope = canonical_pairs([[self.statement, self.note], [self.statement, self.correction],
                                 [self.note, self.correction]])
        self.assertEqual(view["plan"]["pairs"]["needed"], scope)  # Not every pair of visible entries: 3 of 10.
        request = self.saved(view, "request.json")
        self.assertEqual(payload_of(request)["comparison_pairs"], scope)
        self.assertEqual((self.saved(view, "selection.json")["comparison_pairs"],
                          self.saved(view, "prepared.json")["comparison_pairs"],
                          self.saved(view, "selection.json")["triage_version"]), (scope, scope, TRIAGE_VERSION))
        self.assertEqual(request["output_config"]["format"]["schema"]["properties"]["relations"]["items"]["properties"]
                         ["item_ids"]["items"]["enum"],
                         [entry for entry in entry_ids(request) if entry in {self.statement, self.note, self.correction}])
        self.assertIn("listed pairs A-B and B-C do not allow relating A and C", request["system"])
        entries = [row["input"] for row in view["items"]]
        narrower = canonical(build_request(entries, [], scope[:1])).encode("utf-8")
        self.assertNotEqual(sha256(narrower), view["plan"]["request_sha256"])  # The scope is part of the identity.
        for bad in ([list(reversed(scope[0]))], [scope[0], scope[0]], [[self.statement, self.minutes]]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):  # Canonical pairs of supplied IDs only.
                build_request(entries, [], bad)

    def test_reordered_selections_plan_the_same_request_and_scope(self):
        first = self.prepare(self.statement, self.note, self.correction)
        again = self.prepare(self.correction, self.statement, self.note)
        self.assertEqual((again["plan"]["triage_id"], again["plan"]["pairs"]["needed"], again["prepared_now"]),
                         (first["plan"]["triage_id"], first["plan"]["pairs"]["needed"], False))

    def test_a_classification_only_request_allows_no_relation(self):
        view = self.prepare(self.statement, self.jobs, self.july)
        self.assertEqual((view["plan"]["pairs"]["needed"], payload_of(self.saved(view, "request.json"))
                          ["comparison_pairs"]), ([], []))
        rejected = self.approve(view, Provider(relating(self.statement, self.july)))["attempts"]["simulated"]
        self.assertEqual(rejected["outcome"], "not_accepted")
        self.assertIn("planned no comparisons", rejected["message"])
        other = self.prepare(self.note, self.minutes)  # 21 days apart: no pair, results only.
        accepted = self.approve(other, Provider())["attempts"]["simulated"]
        self.assertEqual((accepted["outcome"], accepted["result"]["relations"]), ("triaged", []))


class ResponseScopeTests(Scope):
    """The check on receipt, with the request's own entries and an explicit scope."""

    def setUp(self):
        super().setUp()
        self.entries = [snapshot_item(item) for item in self.items if item["id"] in
                        (self.statement, self.note, self.correction, self.jobs)]

    def parse(self, relations: list[dict], scope: list) -> dict:
        body = reply(results([entry["id"] for entry in self.entries]), relations)[1]
        return parse_response(body, self.entries, [], scope=scope)

    def test_in_scope_relations_are_accepted_with_their_own_member_order_and_wording(self):
        a, b, c = self.statement, self.note, self.correction
        scope = canonical_pairs([[a, b], [b, c], [a, c]])
        parsed = self.parse([{"relation": "possibly_same_event", "item_ids": [a, b, c], "reason": "All three agree."}],
                            scope)
        self.assertEqual(sorted(parsed["relations"][0]["item_ids"]), sorted([a, b, c]))
        update = self.parse([{"relation": "update_or_correction", "item_ids": [c, a], "reason": "c corrects a."}],
                            canonical_pairs([[a, c]]))["relations"][0]
        supplied = [entry["id"] for entry in self.entries]
        # Members keep the request's own order; the canonical pair order never decides it, and the reason is kept.
        self.assertEqual((update["item_ids"], update["reason"]),
                         ([item for item in supplied if item in (a, c)], "c corrects a."))

    def test_every_constituent_pair_must_be_in_scope(self):
        a, b, c = self.statement, self.note, self.correction
        chain = canonical_pairs([[a, b], [b, c]])  # A-B and B-C never allow A-C.
        cases = {
            "a group over an unapproved pair": ([{"relation": "possibly_same_event", "item_ids": [a, b, c],
                                                  "reason": "r"}], chain),
            "an unapproved pair alone": ([{"relation": "separate_releases", "item_ids": [a, c], "reason": "r"}], chain),
            "another publisher": ([{"relation": "separate_releases", "item_ids": [a, self.jobs], "reason": "r"}],
                                  chain),
            "an empty scope": ([{"relation": "separate_releases", "item_ids": [a, b], "reason": "r"}], []),
        }
        for name, (relations, scope) in cases.items():
            with self.subTest(name), self.assertRaises(ResponseRejected) as caught:
                self.parse(relations, scope)
            self.assertTrue("did not plan to compare" in str(caught.exception) or
                            "planned no comparisons" in str(caught.exception), str(caught.exception))
        allowed = self.parse([{"relation": "update_or_correction", "item_ids": [b, c], "reason": "r"},
                              {"relation": "possibly_same_event", "item_ids": [a, b], "reason": "r"}], chain)
        self.assertEqual(len(allowed["relations"]), 2)
        self.assertEqual(self.parse([], [])["relations"], [])  # Results only: accepted with no relation.


class ApprovalScopeTests(Scope):
    def setUp(self):
        super().setUp()
        quick = Provider()
        self.process(self.statement, provider=quick)  # Triaged apart: their pair was never compared.
        self.process(self.note, provider=quick)

    def test_an_approval_must_repeat_exactly_the_saved_scope(self):
        view = self.prepare(self.statement, self.note, self.correction)
        scope = view["plan"]["pairs"]["needed"]
        self.assertEqual(len(scope), 3)
        before, provider = fingerprint(self.triage), Provider(scoped_reply())
        for pairs, status in ((scope[:2], 409), (scope + [[self.statement, self.jobs]], 409),
                              ([[self.note, self.jobs]] + scope[1:], 409), ([], 409),
                              (scope + scope[:1], 422), ([[self.note, self.note]], 422), ([["x"]], 422),
                              ("all", 422)):
            with self.subTest(pairs=pairs), self.assertRaises(TriageRefused) as caught:
                self.approve(view, provider, comparison_pairs=pairs)
            self.assertEqual(caught.exception.status, status)
        self.assertEqual((fingerprint(self.triage), provider.requests), (before, []))  # Nothing claimed or reserved.
        reordered = [list(reversed(pair)) for pair in reversed(scope)]  # Order never matters; the pairs do.
        shown = self.approve(view, provider, comparison_pairs=reordered)
        self.assertEqual((shown["attempts"]["simulated"]["outcome"], len(provider.requests)), ("triaged", 1))
        manifest = json.loads((requests_dir(self.triage) / view["plan"]["triage_id"] / "simulated" / "manifest.json")
                              .read_bytes())
        self.assertEqual(manifest["comparison_pairs"], scope)

    def test_a_stale_approval_is_refused_and_the_saved_bytes_never_change(self):
        stale = self.prepare(self.statement, self.note, self.correction)
        saved = fingerprint(requests_dir(self.triage) / stale["plan"]["triage_id"])
        self.approve(self.prepare(self.statement, self.note), Provider())  # Completes one of its pairs elsewhere.
        provider = Provider()
        with self.assertRaises(TriageRefused) as caught:
            self.approve(stale, provider)
        self.assertIn("comparison work changed", str(caught.exception))
        self.assertEqual((provider.requests, fingerprint(requests_dir(self.triage) / stale["plan"]["triage_id"])),
                         ([], saved))
        fresh = self.prepare(self.statement, self.note, self.correction)
        self.assertEqual(fresh["plan"]["pairs"]["needed"],
                         canonical_pairs([[self.statement, self.correction], [self.note, self.correction]]))
        self.assertNotEqual(fresh["plan"]["triage_id"], stale["plan"]["triage_id"])

    def test_only_requested_comparisons_count_as_done(self):
        """Entries together in one request are not compared unless their pair was in its scope."""
        lost = Provider(lambda request: httpx.ReadTimeout("simulated: no reply"))
        pair_only = self.prepare(self.statement, self.note)
        self.approve(pair_only, lost)  # The statement-note comparison fails: claimed, unresolved.
        added = self.prepare(self.statement, self.note, self.correction)
        self.assertEqual((added["plan"]["entries"], sorted(added["plan"]["context"]), added["plan"]["pairs"]["needed"]),
                         ([self.correction], sorted([self.statement, self.note]),
                          canonical_pairs([[self.statement, self.correction], [self.note, self.correction]])))
        self.approve(added, Provider(scoped_reply()))  # Both appear in this accepted request, as context.
        later = self.view(self.statement, self.note)
        self.assertEqual((later["plan"]["pairs"]["compared"], canonical_pairs(later["plan"]["pairs"]["unresolved"]),
                          later["plan"]["requests"]), (0, canonical_pairs([[self.statement, self.note]]), 0))
        everything = self.view(self.statement, self.note, self.correction)
        self.assertEqual(everything["plan"]["pairs"]["compared"], 2)  # Exactly the two it asked for.
        self.assertTrue(all(relation["scope_checked"] for relation in everything["relations"]))

    def test_a_completed_comparison_is_reused_in_any_order(self):
        self.approve(self.prepare(self.note, self.statement), Provider(scoped_reply()))
        for order in ([self.note, self.statement], [self.statement, self.note]):
            view = self.view(*order)
            self.assertEqual((view["plan"]["requests"], view["plan"]["pairs"]["compared"],
                              [relation["scope_checked"] for relation in view["relations"]]), (0, 1, [True]))


def legacy_record(triage_dir, entries: list[dict], context: list[dict], approved: list | None = None,
                  relations: list[dict] | None = None) -> str:
    """A request saved under headline-triage-0.2, as that version wrote it: no comparison scope in its selection,
    preparation or bytes, and a relation enum over every supplied ID. With ``relations``, an accepted simulated reply
    that relates items freely, as that contract allowed, and an approval naming ``approved`` pairs."""
    supplied = [entry["id"] for entry in entries + context]
    request = build_request(entries, context, [])  # An empty scope keeps every supplied ID in the relation enum.
    request["system"] = request["system"].replace("triage-prompt-3", "triage-prompt-2").replace(
        "triage-schema-3", "triage-schema-2")
    request["messages"][0]["content"] = ("Triage the entries below (headline-triage-0.2).\n\n" +
                                         payload_json(entries, context, None))
    request_bytes = canonical(request).encode("utf-8")
    request_hash = sha256(request_bytes)
    triage_id = f"triage-{request_hash[:24]}"
    folder = requests_dir(triage_dir) / triage_id
    folder.mkdir(parents=True)
    selection = _json_bytes({"triage_version": LEGACY_TRIAGE_VERSION, "triage_id": triage_id, "entries": entries,
                             "context": context})
    (folder / "selection.json").write_bytes(selection)
    (folder / "request.json").write_bytes(request_bytes)
    (folder / "prepared.json").write_bytes(_json_bytes({
        "triage_version": LEGACY_TRIAGE_VERSION, "triage_id": triage_id, "prepared_at": "2026-10-08T12:00:00+00:00",
        "config": {**config(), "prompt_version": "triage-prompt-2", "schema_version": "triage-schema-2"},
        "max_tokens": request["max_tokens"], "request_sha256": request_hash, "request_bytes": len(request_bytes),
        "selection_sha256": sha256(selection), "entry_ids": [entry["id"] for entry in entries],
        "context_ids": [entry["id"] for entry in context],
        "cost_estimate": cost_estimate(request_bytes, request["max_tokens"], context),
        "provenance": "A synthetic headline-triage-0.2 preparation."}))
    if relations is not None:
        body = reply(results([entry["id"] for entry in entries]), relations)[1]
        attempt = folder / "simulated"
        attempt.mkdir()
        (attempt / "response.json").write_bytes(body)
        (attempt / "manifest.json").write_bytes(_json_bytes({
            "triage_id": triage_id, "mode": "simulated", "attempt": "simulated", "model": MODEL,
            "request_sha256": request_hash, "outcome": "triaged", "outcome_note": "Accepted under 0.2.",
            "adapter_message": None, "sent_at": "2026-10-08T12:01:00+00:00",
            "received_at": "2026-10-08T12:01:01+00:00", "http_status": 200, "request_id": "req_fake0001",
            "response": {"sha256": sha256(body), "bytes": len(body)}, "cost": {"usd": 0, "basis": "local simulation"},
            "comparison_pairs": approved or [], "entry_ids": [entry["id"] for entry in entries],
            "context_ids": supplied[len(entries):]}))
    return triage_id


class LegacyTests(Scope):
    def setUp(self):
        super().setUp()
        snapshots = {item["id"]: snapshot_item(item) for item in self.items}
        self.legacy = legacy_record(
            self.triage, [snapshots[item] for item in (self.note, self.statement, self.july)], [],
            approved=[sorted([self.statement, self.note])],
            relations=[{"relation": "possibly_same_event", "item_ids": [self.statement, self.note], "reason": "Same day."},
                       {"relation": "separate_releases", "item_ids": [self.statement, self.july], "reason": "Unbounded."}])
        self.files = fingerprint(requests_dir(self.triage) / self.legacy)

    def test_an_old_preparation_stays_readable_with_its_provenance_and_is_never_sent(self):
        view = request_view(self.legacy, self.triage)
        self.assertEqual((view["record_version"], view["comparison_pairs"], view["sendable"]),
                         (LEGACY_TRIAGE_VERSION, None, False))
        self.assertIn("never sent", view["contract"])
        self.assertEqual(view["attempts"]["simulated"]["outcome"], "triaged")
        (row,) = listing(self.triage)["requests"]
        self.assertEqual((row["state"], row["sendable"], row["comparison_pairs"]), ("ready", False, None))
        provider = Provider()
        record = load_record(self.triage, self.legacy)
        for mode, extra in (("simulated", {"approve_simulated_response": True}),
                            ("paid", {"approve_paid_request": True, "estimated_max_usd": cost_estimate(
                                record["request_bytes"], record["request"]["max_tokens"], [])
                                ["estimated_paid_if_output_reaches_max_usd"]})):
            body = json.dumps({"request_sha256": record["request_sha256"], "reprocess_ids": [entry["id"] for entry in
                                                                                             record["entries"]],
                               "comparison_pairs": [], **extra}).encode()
            with self.subTest(mode=mode), self.assertRaises(TriageRefused) as caught:
                dispatch(self.legacy, mode, body, provider.senders(paid=True), self.triage, lambda: PREPARED_AT)
            self.assertEqual(caught.exception.status, 409)
            self.assertIn(LEGACY, str(caught.exception))
        self.assertEqual((provider.requests, fingerprint(requests_dir(self.triage) / self.legacy)), ([], self.files))
        self.assertFalse((self.triage / "claims").exists())

    def test_legacy_results_stay_historical_and_nothing_is_regenerated_on_its_own(self):
        view = self.view(self.statement, self.note, self.july)
        self.assertEqual({row["status"] for row in view["items"]}, {"earlier_version"})
        self.assertEqual(view["plan"]["requests"], 0)  # A version change requests nothing by itself.
        # Only the pair its approval named counts, as work of the earlier configuration: never queued on its own.
        self.assertEqual(canonical_pairs(view["plan"]["pairs"]["earlier"]), canonical_pairs([[self.statement, self.note]]))
        shown = {relation["relation"]: relation for relation in view["relations"]}
        self.assertEqual(set(shown), {"possibly_same_event", "separate_releases"})
        self.assertTrue(all(relation["scope_checked"] is False for relation in shown.values()))
        self.assertTrue(all(relation["provenance"]["triage_id"] == self.legacy for relation in shown.values()))
        regenerate = self.prepare(self.statement, self.note, self.july, reprocess=[self.statement, self.note])
        self.assertEqual(regenerate["plan"]["pairs"]["needed"], canonical_pairs([[self.statement, self.note]]))
        self.assertNotEqual(regenerate["plan"]["triage_id"], self.legacy)
        self.assertEqual(fingerprint(requests_dir(self.triage) / self.legacy), self.files)

    def test_a_tampered_scope_does_not_verify_and_is_left_alone(self):
        view = self.prepare(self.statement, self.correction)
        folder = requests_dir(self.triage) / view["plan"]["triage_id"]
        for name in ("selection.json", "prepared.json"):
            original = (folder / name).read_bytes()
            saved = json.loads(original)
            saved["comparison_pairs"] = []
            (folder / name).write_bytes(_json_bytes(saved))
            with self.subTest(name), self.assertRaises(TriageRefused) as caught:
                load_record(self.triage, view["plan"]["triage_id"])
            self.assertIn("does not verify", str(caught.exception))
            (folder / name).write_bytes(original)
        self.assertEqual(load_record(self.triage, view["plan"]["triage_id"])["pairs"],
                         canonical_pairs([[self.statement, self.correction]]))


class ReadOnlyTests(Scope):
    def test_reads_make_no_write_and_no_provider_call(self):
        provider = Provider(scoped_reply())
        legacy = legacy_record(self.triage, [snapshot_item(item) for item in self.items if item["id"] == self.july], [])
        self.approve(self.prepare(self.statement, self.note), provider)
        before, calls = fingerprint(self.root), len(provider.requests)
        blocked = AssertionError("a read tried to open a network connection")
        app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                         self.root / "intake", self.root / "attempts", inbox=self.inbox, feeds=Network({}).fetcher(),
                         triage=self.triage, triage_senders=provider.senders(paid=True))
        with TestClient(app, base_url=BASE) as client, patch("socket.create_connection", side_effect=blocked), \
                patch("socket.getaddrinfo", side_effect=blocked):
            for mode in ("simulated", "paid"):
                for ids in ([self.statement, self.note], [self.statement, self.note, self.correction,
                                                          self.id(GENERIC)]):
                    self.assertEqual(client.get("/api/triage/selection", params={"mode": mode, "ids": ids})
                                     .status_code, 200)
            listed = client.get("/api/triage").json()
            self.assertEqual({row["triage_id"]: row["sendable"] for row in listed["requests"]}[legacy], False)
            for row in listed["requests"]:
                self.assertEqual(client.get(f"/api/triage/{row['triage_id']}").status_code, 200)
        self.assertEqual((fingerprint(self.root), len(provider.requests)), (before, calls))


if __name__ == "__main__":
    unittest.main()

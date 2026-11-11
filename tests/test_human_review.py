"""Persistent human review of prepared drafts: append-only versions, provenance binding and write safety.

Drafts here are synthetic. A saved status records a person's judgment; nothing here verifies reasoning.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from draft_attempts import write_attempt
from second_order.api import create_app
from second_order.draft_views import prepare_drafts
from second_order.human_review import (ATTRIBUTION, HISTORY_VERSION, MAX_BODY, MAX_NOTES, RECORD_VERSION,
                                       ReviewRefused, review_id, save_review)
from second_order.store import digest

BASE = "http://127.0.0.1:8000"
HEADERS = {"Origin": BASE, "X-Second-Order-Review": "1", "Content-Type": "application/json"}


def files(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.pilot, self.drafts = self.root / "pilot", self.root / "prepared-drafts"
        self.reviews = self.root / "reviews"
        attempts = [write_attempt(self.pilot / kind, kind, kind) for kind in ("draft", "no-draft", "technical-failure")]
        index = prepare_drafts(attempts, self.drafts, self.pilot)
        self.ids = {row["case"]: row["id"] for row in index["drafts"]}
        self.views = {case: json.loads((self.drafts / f"draft-{draft_id}.json").read_text(encoding="utf-8"))
                      for case, draft_id in self.ids.items()}
        self.client = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews), base_url=BASE)
        self.addCleanup(self.client.close)
        self.loaded = {case: self.load(case) for case in self.ids}  # The fingerprint each page would hold.

    def load(self, case: str) -> str:
        """Load a draft as the page does and return the fingerprint served with it."""
        response = self.client.get(f"/api/drafts/{self.ids[case]}")
        self.assertEqual(response.headers["x-draft-view-sha256"], hashlib.sha256(response.content).hexdigest())
        return response.headers["x-draft-view-sha256"]

    def payload(self, case: str = "draft", parent: str | None = None, **changes) -> dict:
        provenance = self.views[case]["provenance"]
        body = {"parent_review_id": parent, "status": "needs_revision", "notes": "Source does not state pricing.",
                "binding": {"draft_view_sha256": self.loaded[case], "prompt_hash": provenance["prompt_hash"],
                            "response_sha256": provenance["response_sha256"]},
                "corrections": {"summary": None, "legs": {}}}
        return {**body, **changes}

    def save(self, case: str = "draft", body: dict | bytes | None = None, headers: dict | None = None,
             draft_id: str | None = None):
        data = body if isinstance(body, bytes) else json.dumps(self.payload(case) if body is None else body).encode()
        return self.client.post(f"/api/drafts/{draft_id or self.ids[case]}/reviews", content=data,
                                headers=HEADERS if headers is None else headers)

    def history(self, case: str = "draft") -> list[dict]:
        response = self.client.get(f"/api/drafts/{self.ids[case]}/reviews")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["view_version"], HISTORY_VERSION)
        view_file = self.drafts / f"draft-{self.ids[case]}.json"
        self.assertEqual(response.json()["draft_view_sha256"], hashlib.sha256(view_file.read_bytes()).hexdigest())
        return response.json()["reviews"]

    def test_a_save_appends_an_immutable_version_bound_to_what_was_reviewed(self):
        draft = self.views["draft"]["draft"]
        corrections = {"summary": "A human-corrected summary that names the competing channel.",
                       "legs": {"primary": {"rationale": "Corrected rationale.", "headline_reports_move": True},
                                "secondary": {"falsifier": "Corrected falsifier."}}}
        before_prepared, before_pilot = files(self.drafts), files(self.pilot)
        started = datetime.now().astimezone()
        response = self.save(body=self.payload(corrections=corrections, saved_at="2020-01-01T00:00:00Z"))
        self.assertEqual(response.status_code, 422)  # The client cannot stamp the time.
        response = self.save(body=self.payload(corrections=corrections))
        self.assertEqual(response.status_code, 201, response.text)
        record = response.json()
        self.assertEqual((record["record_version"], record["sequence"], record["parent_review_id"],
                          record["attributed_to"]), (RECORD_VERSION, 1, None, ATTRIBUTION))
        self.assertGreaterEqual(datetime.fromisoformat(record["saved_at"]), started)  # Stamped by the server.
        self.assertEqual(record["review_id"], review_id(record))
        self.assertEqual(record["review_id"],
                         digest({key: value for key, value in record.items() if key != "review_id"}))
        provenance = self.views["draft"]["provenance"]
        view_file = self.drafts / f"draft-{self.ids['draft']}.json"
        self.assertEqual(record["binding"], {
            "draft_view_sha256": hashlib.sha256(view_file.read_bytes()).hexdigest(),
            "draft_view_version": "draft-review-view-0.1", "outcome": "draft",
            "prompt_hash": provenance["prompt_hash"], "response_sha256": provenance["response_sha256"],
            "request_id": provenance["request_id"], "pilot": provenance["pilot"], "case": provenance["case"]})
        self.assertEqual((record["status"], record["corrections"]), ("needs_revision", corrections))
        self.assertEqual(json.loads((self.reviews / self.ids["draft"] / "000001.json").read_text(encoding="utf-8")),
                         record)
        self.assertEqual(self.history(), [record])
        self.assertEqual(self.views["draft"]["draft"], draft)  # The model's proposal is untouched...
        self.assertEqual((files(self.drafts), files(self.pilot)), (before_prepared, before_pilot))  # ...and its files.

    def test_a_changed_view_refuses_stale_saves_and_keeps_earlier_versions_apart(self):
        view_file = self.drafts / f"draft-{self.ids['draft']}.json"
        corrected = {"summary": "A human-corrected summary.", "legs": {"primary": {"falsifier": "Corrected."}}}
        first = self.save(body=self.payload(corrections=corrected)).json()
        first_bytes = (self.reviews / self.ids["draft"] / "000001.json").read_bytes()
        loaded = self.payload(parent=first["review_id"], notes="A second thought on the view I loaded.")
        # Prepared again with another summary: the prompt and response hashes are the same, the view is not.
        view = json.loads(view_file.read_text(encoding="utf-8"))
        view["draft"]["summary"] = "A different summary prepared later."
        view_file.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                             encoding="utf-8")
        self.assertEqual(view["provenance"], self.views["draft"]["provenance"])
        response = self.save(body=loaded)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("changed since it was loaded", response.json()["detail"])
        self.assertEqual(sorted(path.name for path in (self.reviews / self.ids["draft"]).iterdir()), ["000001.json"])
        current = hashlib.sha256(view_file.read_bytes()).hexdigest()
        self.assertEqual(self.load("draft"), current)
        reviews = self.history()  # Reports the current fingerprint, which the earlier version does not carry.
        self.assertEqual(reviews, [first])
        self.assertNotEqual(reviews[0]["binding"]["draft_view_sha256"], current)
        # Against the view now served, the same judgment is a new version, not "nothing changed".
        self.loaded["draft"] = current
        again = self.save(body=self.payload(parent=first["review_id"], corrections=corrected))
        self.assertEqual(again.status_code, 201, again.text)
        self.assertEqual((again.json()["sequence"], again.json()["binding"]["draft_view_sha256"]), (2, current))
        self.assertEqual((self.reviews / self.ids["draft"] / "000001.json").read_bytes(), first_bytes)
        self.assertEqual(self.save(body=self.payload(parent=again.json()["review_id"], corrections=corrected))
                         .status_code, 422)  # Unchanged against the same view.

    def test_versions_append_and_stale_parents_are_refused(self):
        first = self.save().json()
        first_bytes = (self.reviews / self.ids["draft"] / "000001.json").read_bytes()
        second = self.save(body=self.payload(parent=first["review_id"], status="human_reviewed"))
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual((second.json()["sequence"], second.json()["parent_review_id"]), (2, first["review_id"]))
        self.assertEqual((self.reviews / self.ids["draft"] / "000001.json").read_bytes(), first_bytes)  # Untouched.
        self.assertEqual([item["review_id"] for item in self.history()],
                         [first["review_id"], second.json()["review_id"]])
        refusals = {"stale parent": (self.payload(parent=first["review_id"], notes="Other"), 409),
                    "no parent although history exists": (self.payload(notes="Other"), 409),
                    "nothing changed": (self.payload(parent=second.json()["review_id"], status="human_reviewed"), 422),
                    "unknown parent": (self.payload(parent="a" * 64, notes="Other"), 409)}
        for name, (body, status) in refusals.items():
            with self.subTest(name):
                self.assertEqual(self.save(body=body).status_code, status)
        self.assertEqual(len(self.history()), 2)

    def test_racing_saves_on_one_parent_leave_exactly_one_version(self):
        start, outcomes = threading.Barrier(6), []

        def attempt(number: int):
            body = json.dumps(self.payload(notes=f"Racing note {number}")).encode()
            start.wait()
            try:
                outcomes.append(save_review(self.drafts, self.reviews, self.ids["draft"], body)["sequence"])
            except ReviewRefused as exc:
                outcomes.append(exc.status)

        threads = [threading.Thread(target=attempt, args=(number,)) for number in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), [1, 409, 409, 409, 409, 409])
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(sorted(path.name for path in (self.reviews / self.ids["draft"]).iterdir()), ["000001.json"])

    def test_provenance_binding_and_identifiers_are_checked(self):
        stale = self.payload()
        stale["binding"]["prompt_hash"] = "0" * 64
        self.assertEqual(self.save(body=stale).status_code, 409)
        for draft_id, status in (("f" * 64, 404), ("not-an-id", 404), ("F" * 64, 404)):
            with self.subTest(draft_id=draft_id):
                self.assertEqual(self.save(draft_id=draft_id).status_code, status)
                self.assertEqual(self.client.get(f"/api/drafts/{draft_id}/reviews").status_code, status)
        view_file = self.drafts / f"draft-{self.ids['draft']}.json"
        view_file.write_text(json.dumps({**self.views["draft"], "id": "e" * 64}), encoding="utf-8")
        self.assertEqual(self.save().status_code, 409)  # A prepared view that does not match its ID is refused.
        with TestClient(create_app(self.root / "no-dossiers", None, self.root / "missing", self.reviews),
                        base_url=BASE) as client:
            self.assertEqual(client.get(f"/api/drafts/{self.ids['draft']}/reviews").status_code, 503)
        self.assertFalse(self.reviews.exists())

    def test_malformed_reviews_are_refused_and_nothing_is_written(self):
        legs = lambda **fields: {"summary": None, "legs": {"primary": fields}}  # noqa: E731
        original = self.views["draft"]["draft"]
        cases = {
            "not JSON": b"{not json", "a JSON array": b"[]",
            "repeated key": b'{"notes": "a", "notes": "b"}',
            "NaN": json.dumps(self.payload()).replace('"needs_revision"', "NaN").encode(),
            "extra field": self.payload(approved=True),
            "missing field": {key: value for key, value in self.payload().items() if key != "status"},
            "malformed parent": self.payload(parent="abc"),
            "binding with an extra key": self.payload(binding={**self.payload()["binding"], "model": "x"}),
            "binding without the view fingerprint": self.payload(binding={
                key: value for key, value in self.payload()["binding"].items() if key != "draft_view_sha256"}),
            "fingerprint not a hash": self.payload(binding={**self.payload()["binding"], "draft_view_sha256": "x"}),
            "unknown status": self.payload(status="approved"),
            "notes not text": self.payload(notes=5),
            "notes too long": self.payload(notes="x" * (MAX_NOTES + 1)),
            "control character": self.payload(notes="bell\x07"),
            "empty review": self.payload(status=None, notes="   "),
            "summary unchanged": self.payload(corrections={"summary": original["summary"], "legs": {}}),
            "summary padded": self.payload(corrections={"summary": " Padded summary", "legs": {}}),
            "summary empty": self.payload(corrections={"summary": "", "legs": {}}),
            "unknown leg": self.payload(corrections={"summary": None, "legs": {"other": {"rationale": "x"}}}),
            "direction is not editable": self.payload(corrections=legs(expected="up")),
            "horizon is not editable": self.payload(corrections=legs(horizon=20)),
            "observable is not editable": self.payload(corrections=legs(observable_id="yield:ust10y_cmt")),
            "primary leg is not editable": self.payload(corrections=legs(primary=False)),
            "flag as text": self.payload(corrections=legs(headline_reports_move="true")),
            "flag unchanged": self.payload(corrections=legs(headline_reports_move=False)),
            "empty leg correction": self.payload(corrections=legs()),
            "corrections without legs": self.payload(corrections={"summary": None}),
            "graph is not editable": self.payload(corrections={"summary": None, "legs": {}, "nodes": []}),
        }
        for name, body in cases.items():
            with self.subTest(name):
                response = self.save(body=body)
                self.assertEqual(response.status_code, 422, response.text)
        oversized = self.save(body=self.payload(notes="x" * MAX_BODY))
        self.assertEqual(oversized.status_code, 413)
        self.assertFalse(self.reviews.exists())

    def test_declines_and_failures_take_notes_but_never_corrections(self):
        for case in ("no-draft", "technical-failure"):
            with self.subTest(case):
                refused = self.save(case, self.payload(case, corrections={"summary": "Invented draft", "legs": {}}))
                self.assertEqual(refused.status_code, 422)
                self.assertIn("only to a model draft", refused.json()["detail"])
                saved = self.save(case)
                self.assertEqual(saved.status_code, 201, saved.text)
                self.assertEqual(saved.json()["corrections"], {"summary": None, "legs": {}})
                self.assertEqual(saved.json()["binding"]["outcome"], self.views[case]["outcome"])
        self.assertIsNone(self.history("technical-failure")[0]["binding"]["response_sha256"])

    def test_writes_are_refused_unless_they_are_same_origin_local_json(self):
        cases = {
            "no Origin": ({key: value for key, value in HEADERS.items() if key != "Origin"}, 403),
            "another origin": ({**HEADERS, "Origin": "http://evil.example"}, 403),
            "another local port": ({**HEADERS, "Origin": "http://127.0.0.1:9999"}, 403),
            "cross-site fetch": ({**HEADERS, "Sec-Fetch-Site": "cross-site"}, 403),
            "no review header": ({key: value for key, value in HEADERS.items() if key != "X-Second-Order-Review"}, 403),
            "plain text": ({**HEADERS, "Content-Type": "text/plain"}, 415),
            "form post": ({**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}, 415),
            "declared too large": ({**HEADERS, "Content-Length": str(MAX_BODY + 1)}, 413),
        }
        for name, (headers, status) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.save(headers=headers).status_code, status)
        rebinding = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews),
                               base_url="http://evil.example:8000")
        with rebinding:  # A DNS-rebound name: same-origin to the browser, but not a local address.
            response = rebinding.post(f"/api/drafts/{self.ids['draft']}/reviews", content=json.dumps(self.payload()),
                                      headers={**HEADERS, "Origin": "http://evil.example:8000"})
            self.assertEqual(response.status_code, 403)
        preflight = self.client.options(f"/api/drafts/{self.ids['draft']}/reviews",
                                        headers={"Origin": "http://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
        self.assertEqual(preflight.status_code, 405)
        self.assertNotIn("access-control-allow-origin", preflight.headers)
        self.assertFalse(self.reviews.exists())
        self.assertEqual(self.save().status_code, 201)  # The local page's own request is accepted.

    def test_only_the_explicit_local_action_routes_write(self):
        writes = {route.path: route.methods - {"GET", "HEAD"} for route in self.client.app.routes
                  if getattr(route, "methods", None) and route.methods - {"GET", "HEAD"}}
        self.assertEqual(writes, {"/api/drafts/{draft_id}/reviews": {"POST"},
                                  "/api/intake": {"POST"},
                                  "/api/intake/{capture_id}/mock-drafts": {"POST"},
                                  "/api/intake/{capture_id}/publish": {"POST"},
                                  "/api/intake/{capture_id}/paid-drafts": {"POST"},
                                  "/api/inbox/refresh": {"POST"},  # The explicit, local-only inbox refresh.
                                  "/api/triage": {"POST"},  # Headline triage: prepare a selection,
                                  "/api/triage/{triage_id}/{mode}": {"POST"},  # then approve one response,
                                  "/api/triage/{triage_id}/{attempt}/revalidate": {"POST"},  # or re-check one locally.
                                  # Market context: confirm a context date, or send one approved request.
                                  "/api/market-context/inbox/{item_id}/confirm": {"POST"},
                                  "/api/market-context/retrievals": {"POST"},
                                  # The lifecycle: upgrade the store, import a baseline locally, preview (writes
                                  # nothing) and approve one freeze.
                                  "/api/lifecycle/store-upgrade": {"POST"}, "/api/lifecycle/baselines": {"POST"},
                                  "/api/lifecycle/preview": {"POST"}, "/api/lifecycle/freezes": {"POST"},
                                  # Assessment: import an outcome, preview, evaluate and prepare, prepare a Dossier,
                                  # preview an outcome retrieval and send one approved request.
                                  "/api/lifecycle/outcome-imports": {"POST"},
                                  "/api/lifecycle/assessment-preview": {"POST"}, "/api/lifecycle/assessments": {"POST"},
                                  "/api/lifecycle/dossier-preparations": {"POST"},
                                  "/api/lifecycle/retrieval-preview": {"POST"}, "/api/lifecycle/retrievals": {"POST"},
                                  # Findings: the explicit local check of retained evidence.
                                  "/api/insights/checks": {"POST"},
                                  # Industry findings: the explicit local check of retained G.17 releases.
                                  "/api/insights/g17/checks": {"POST"},
                                  # Electricity findings: the explicit local computation from retained Table 7.6.
                                  "/api/insights/electricity/checks": {"POST"},
                                  # Cross-source comparisons: the explicit local computation from both sources.
                                  "/api/insights/cross-source/checks": {"POST"},
                                  # The copper tools: preview a scenario (writes nothing) and save one
                                  # write-once record.
                                  "/api/tools/copper/preview": {"POST"}, "/api/tools/copper/scenarios": {"POST"},
                                  # The capital-recovery panel: computes for entered inputs, writes nothing.
                                  "/api/tools/copper/capital-charge": {"POST"},
                                  # The FCX Scenarios tab: one exact calculation for entered inputs, writes nothing.
                                  "/api/companies/fcx/scenario": {"POST"},
                                  # Event chains: the owner's review and reading, each one append-only record.
                                  "/api/theses/copper/event-chains/{chain_id}/reviews": {"POST"},
                                  "/api/theses/copper/event-chains/{chain_id}/readings": {"POST"},
                                  # Copper research: the owner's note, one append-only record.
                                  "/api/theses/copper/research/notes": {"POST"},
                                  # Related Cases: the explicit local check of one event against the historical cases.
                                  "/api/related-cases/events/{kind}/{event_id}/matches": {"POST"},
                                  # The retained BIS snapshot: open it (its index, once), preview an import (writes
                                  # nothing) and import the selection into the Event Inbox (local and free).
                                  "/api/inbox/snapshots/bis/open": {"POST"}, "/api/inbox/snapshots/bis/preview": {"POST"},
                                  "/api/inbox/snapshots/bis/import": {"POST"},
                                  # Evidence-first research analysis: prepare a request (nothing is sent), approve
                                  # one mock response, send one approved paid request and append a review version.
                                  "/api/research-analyses": {"POST"}, "/api/research-analyses/{request_id}/mock": {"POST"},
                                  "/api/research-analyses/{request_id}/paid": {"POST"},
                                  "/api/research-analyses/{request_id}/reviews": {"POST"},
                                  # Accounts: sign in and out; a user's source, analysis, quote, approved run and
                                  # review; the administrator's attributed account, credit and policy actions.
                                  "/api/session/login": {"POST"}, "/api/session/logout": {"POST"},
                                  "/api/user/sources": {"POST"}, "/api/user/analyses": {"POST"},
                                  "/api/user/analyses/{analysis_id}/quotes": {"POST"},
                                  "/api/user/analyses/{analysis_id}/runs": {"POST"},
                                  "/api/user/analyses/{analysis_id}/reviews": {"POST"},
                                  "/api/admin/users": {"POST"}, "/api/admin/users/{user_id}/status": {"POST"},
                                  "/api/admin/users/{user_id}/credits": {"POST"},
                                  "/api/admin/users/{user_id}/daily-limit": {"POST"},
                                  "/api/admin/attempts/{attempt_id}/resolve": {"POST"},
                                  "/api/admin/policy": {"POST"}, "/api/admin/settings": {"POST"},
                                  "/api/admin/ownership": {"POST"},
                                  # Onboarding: a public registration (a pending account only), an administrator's
                                  # one decision on it, and a policy preview that records nothing.
                                  "/api/public/registrations": {"POST"},
                                  "/api/admin/registrations/{user_id}/decision": {"POST"},
                                  "/api/admin/policy/preview": {"POST"},
                                  # Current news: a user's interests, a counted search, an import preview and its
                                  # confirmation; the administrator's usage limits.
                                  "/api/user/news/interests": {"POST"}, "/api/user/news/searches": {"POST"},
                                  "/api/user/news/imports": {"POST"},
                                  "/api/user/news/imports/{import_id}/confirmation": {"POST"},
                                  "/api/admin/usage-policy": {"POST"},
                                  # News stories: a user's Go deeper (their own source and prepared analysis); the
                                  # News desk's explicit refresh, grouping, curation, briefs, topics, priority and the
                                  # paid draft's preview and approval.
                                  "/api/user/news/stories/{story_id}/deeper": {"POST"},
                                  "/api/admin/news/feeds/refresh": {"POST"}, "/api/admin/news/group": {"POST"},
                                  "/api/admin/news/stories/{story_id}/merge": {"POST"},
                                  "/api/admin/news/stories/{story_id}/detach": {"POST"},
                                  "/api/admin/news/stories/{story_id}/title": {"POST"},
                                  "/api/admin/news/stories/{story_id}/briefs": {"POST"},
                                  "/api/admin/news/stories/{story_id}/publication": {"POST"},
                                  "/api/admin/news/topics": {"POST"}, "/api/admin/news/topics/{topic_id}/links": {"POST"},
                                  "/api/admin/news/priorities": {"POST"},
                                  "/api/admin/news/stories/{story_id}/drafting": {"POST"},
                                  "/api/admin/news/drafting/{draft_id}/approval": {"POST"},
                                  # Texts, reviews, material judgements and batches (the second milestone).
                                  "/api/admin/news/stories/{story_id}/texts": {"POST"},
                                  "/api/admin/news/stories/{story_id}/reviews": {"POST"},
                                  "/api/admin/news/stories/{story_id}/assessment": {"POST"},
                                  "/api/admin/news/batches": {"POST"},
                                  "/api/admin/news/batches/{batch_id}/approval": {"POST"},
                                  "/api/admin/news/batches/{batch_id}/publication": {"POST"},
                                  # Relevance judgements and assessment batches (the third milestone).
                                  "/api/admin/news/stories/{story_id}/relevance": {"POST"},
                                  "/api/admin/news/relevance/batches": {"POST"},
                                  "/api/admin/news/relevance/batches/{batch_id}/approval": {"POST"},
                                  "/api/admin/news/matches": {"POST"},
                                  # An update run's start, refresh, texts and step previews.
                                  "/api/admin/news/updates": {"POST"},
                                  "/api/admin/news/updates/{run_id}/refresh": {"POST"},
                                  "/api/admin/news/updates/{run_id}/texts": {"POST"},
                                  "/api/admin/news/updates/{run_id}/relevance": {"POST"},
                                  "/api/admin/news/updates/{run_id}/context": {"POST"},
                                  "/api/admin/news/updates/{run_id}/briefs": {"POST"}})
        draft = f"/api/drafts/{self.ids['draft']}"
        for method, path in (("post", draft), ("put", f"{draft}/reviews"), ("delete", f"{draft}/reviews"),
                             ("post", "/api/drafts"), ("post", "/api/dossiers")):
            with self.subTest(method=method, path=path):
                self.assertEqual(getattr(self.client, method)(path, headers=HEADERS).status_code, 405)

    def test_a_tampered_history_is_reported_and_never_repaired(self):
        first = self.save().json()
        folder = self.reviews / self.ids["draft"]
        (folder / ".tmp-leftover").write_bytes(b"partial")  # A crashed writer's temporary file is ignored.
        self.assertEqual(len(self.history()), 1)
        tampers = {
            "edited content": lambda: (folder / "000001.json").write_text(
                json.dumps({**first, "notes": "Edited later"}), encoding="utf-8"),
            "gap in numbering": lambda: (folder / "000003.json").write_text("{}", encoding="utf-8"),
            "unexpected file": lambda: (folder / "notes.txt").write_text("x", encoding="utf-8"),
        }
        original = (folder / "000001.json").read_bytes()
        for name, tamper in tampers.items():
            with self.subTest(name):
                tamper()
                response = self.client.get(f"/api/drafts/{self.ids['draft']}/reviews")
                self.assertEqual(response.status_code, 500)
                self.assertIn("inconsistent", response.json()["detail"])
                self.assertEqual(self.save(body=self.payload(parent=first["review_id"], notes="Next")).status_code, 500)
                for extra in ("000003.json", "notes.txt"):
                    (folder / extra).unlink(missing_ok=True)
                (folder / "000001.json").write_bytes(original)

    def test_reviews_never_land_in_prepared_or_pilot_records(self):
        body = json.dumps(self.payload()).encode()
        with self.assertRaisesRegex(ReviewRefused, "inside prepared or pilot records"):
            save_review(self.drafts, self.drafts / "reviews", self.ids["draft"], body)
        with patch("second_order.human_review.PILOT_ROOT", self.pilot), \
                self.assertRaisesRegex(ReviewRefused, "inside prepared or pilot records"):
            save_review(self.drafts, self.pilot / "reviews", self.ids["draft"], body)
        self.assertFalse((self.drafts / "reviews").exists() or (self.pilot / "reviews").exists())


if __name__ == "__main__":
    unittest.main()

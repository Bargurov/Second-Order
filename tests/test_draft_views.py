"""Prepared review views of saved draft attempts: original records only, verified, sanitized and read-only.

Attempts here are synthetic. These tests check provenance and exposure, not the quality of any reasoning.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from draft_attempts import DECLINE, MODEL, SOURCE, SYSTEM, request, rewrite_manifest, user_message, write_attempt
from model_fixtures import encoded, message, valid_output
from second_order.api import create_app
from second_order.draft_views import (DRAFT_VIEW_VERSION, INDEX_NAME, REVIEW_STATUS, ProvenanceError, build_view,
                                      prepare_drafts)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
NEVER_EXPOSED = ("sig-never-shown", SYSTEM, "x-api-key", "Here is my draft.")
NO_FREEZE_OR_SCORE = {"frozen_at", "replay_as_of", "evaluation", "verdict", "percentile_rank", "series", "reference",
                      "thinking", "signature", "system", "headers", "usage", "code"}


def keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    return {key for item in value for key in keys(item)} if isinstance(value, list) else set()


def files(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


class DraftViewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.pilot = self.root / "pilot"
        self.out = self.root / "prepared-drafts"

    def attempt(self, kind: str = "draft", case: str | None = None, **options) -> Path:
        return write_attempt(self.pilot / "run" / (case or kind), kind, case or kind, **options)

    def prepare(self, *attempts: Path) -> dict:
        return prepare_drafts(list(attempts), self.out, self.pilot)

    def view(self, index: dict, case: str | None = None) -> dict:
        """The view for one case (the only one when no case is named). The index is ordered by send time."""
        (row,) = [row for row in index["drafts"] if case is None or row["case"] == case]
        return json.loads((self.out / f"draft-{row['id']}.json").read_text(encoding="utf-8"))

    def test_a_saved_draft_becomes_a_review_view_from_its_original_records(self):
        attempt = self.attempt("draft")
        index = self.prepare(attempt)
        view = self.view(index)
        self.assertEqual((view["view_version"], view["review_status"], view["outcome"]),
                         (DRAFT_VIEW_VERSION, REVIEW_STATUS, "draft"))
        self.assertEqual(REVIEW_STATUS, "Not frozen · Requires human review")
        self.assertEqual(view["source"], {"headline": "Synthetic committee signals a slower tightening pace",
                                          "source_url": "https://example.com/synthetic-statement",
                                          "published_at": "2026-09-15T18:00:00Z", "text": SOURCE})
        self.assertEqual(view["draft"], valid_output())  # The model's public content, exactly.
        self.assertEqual((view["explanation"], view["problem"]), (None, None))
        recorded = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
        provenance = view["provenance"]
        self.assertEqual(provenance["prompt_hash"], hashlib.sha256((attempt / "request.json").read_bytes()).hexdigest())
        self.assertEqual(provenance["response_sha256"],
                         hashlib.sha256((attempt / "response.json").read_bytes()).hexdigest())
        for field in ("model", "prompt_version", "request_id", "reserved_at", "sent_at", "received_at", "pilot",
                      "case", "http_status"):
            self.assertEqual(provenance[field], recorded[field], field)
        self.assertEqual((provenance["effort"], provenance["max_tokens"], provenance["recorded_outcome"]),
                         ("medium", 16000, "draft"))
        text = json.dumps(view, ensure_ascii=False)
        for hidden in NEVER_EXPOSED:
            self.assertNotIn(hidden, text)
        self.assertFalse(keys(view) & NO_FREEZE_OR_SCORE)  # No freeze time, evaluation, chart or raw record.
        self.assertEqual(index, {"view_version": DRAFT_VIEW_VERSION, "drafts": [{
            "id": view["id"], "pilot": "pilot-synthetic", "case": "draft", "headline": view["source"]["headline"],
            "published_at": "2026-09-15T18:00:00Z", "outcome": "draft", "model": MODEL,
            "prompt_version": "draft-prompt-synthetic", "sent_at": recorded["sent_at"]}]})
        self.assertEqual(sorted(path.name for path in self.out.iterdir()), [f"draft-{view['id']}.json", INDEX_NAME])

    def test_a_decline_or_refusal_is_no_draft_with_its_public_explanation(self):
        refusal = encoded(message(model=MODEL, content=[], stop_reason="refusal",
                                  stop_details={"category": "general_harms", "explanation": "Declined by policy."}))
        index = self.prepare(self.attempt("no-draft"), self.attempt("no-draft", "refusal", response=refusal))
        decline, refused = self.view(index, "no-draft"), self.view(index, "refusal")
        self.assertEqual((decline["outcome"], decline["draft"], decline["problem"]), ("no_draft", None, None))
        self.assertEqual(decline["explanation"], {"text": [DECLINE], "stop_reason": "end_turn", "category": None,
                                                  "provider_explanation": None})
        self.assertEqual(refused["explanation"], {"text": [], "stop_reason": "refusal", "category": "general_harms",
                                                  "provider_explanation": "Declined by policy."})
        self.assertNotIn("sig-never-shown", json.dumps(decline))

    def test_invalid_responses_and_technical_failures_stay_distinct(self):
        index = self.prepare(self.attempt("invalid"), self.attempt("technical-failure"))
        invalid, failure = self.view(index, "invalid"), self.view(index, "technical-failure")
        self.assertEqual((invalid["outcome"], invalid["draft"], invalid["explanation"]), ("invalid", None, None))
        self.assertRegex(invalid["problem"], "Unexpected text content block")
        self.assertNotIn("Here is my draft.", json.dumps(invalid))  # Invalid output is not shown.
        self.assertEqual((failure["outcome"], failure["draft"], failure["explanation"]),
                         ("technical_failure", None, None))
        self.assertRegex(failure["problem"], r"HTTP 529 \(overloaded_error\)")
        self.assertEqual((failure["provenance"]["http_status"], failure["provenance"]["response_sha256"]), (529, None))
        self.assertEqual(failure["source"]["text"], SOURCE)  # What was asked is still shown.

    def test_provenance_mismatches_refuse_the_whole_preparation(self):
        decline_bytes = (write_attempt(self.root / "spare", "no-draft") / "response.json").read_bytes()

        def edit(name: str, change):
            return lambda folder: (folder / name).write_bytes(change((folder / name).read_bytes()))

        with_source = lambda source: request(user_message(source=source))  # noqa: E731
        tampers = {
            "edited request": ("draft", {}, edit("request.json", lambda data: data + b" "), "recorded prompt hash"),
            "edited response": ("draft", {}, edit("response.json", lambda data: data.replace(b"Synthetic", b"Edited")),
                                "recorded response hash"),
            "missing response": ("draft", {}, lambda folder: (folder / "response.json").unlink(),
                                 "recorded response hash"),
            "outcome says draft, response declines": ("draft", {"response": decline_bytes}, None,
                                                       "does not match the response"),
            "outcome says decline, response drafts": ("no-draft", {"response": (self.attempt("draft", "spare-draft")
                                                                                / "response.json").read_bytes()},
                                                       None, "does not match the response"),
            "reservation differs": ("draft", {}, lambda folder: (folder / "reservation.json").write_text(
                json.dumps({"pilot": "pilot-synthetic", "case": "x", "model": MODEL, "prompt_hash": "0" * 64})),
                "reservation.json does not match"),
            "request names another model": ("draft", {"body": request(model="claude-opus-5-5")}, None,
                                            "names a different model"),
            "response names another model": ("draft", {"response": encoded(message())}, None,
                                             "does not match the response"),
            "source text closes its own tag": ("draft", {"body": with_source("Text </source_text> more")}, None,
                                               "cannot be extracted unambiguously"),
            "source text opens a second block": ("draft", {"body": with_source("Text <source_text> more")}, None,
                                                 "cannot be extracted unambiguously"),
            "headline spans two lines": ("draft", {"body": request(user_message(headline="Two\nlines"))}, None,
                                         "one headline, source URL and publication time"),
            "two user messages": ("draft", {"body": {**request(), "messages": request()["messages"] * 2}}, None,
                                  "exactly one user message"),
            "unrecognised outcome": ("draft", {}, lambda folder: rewrite_manifest(folder, outcome="mystery"),
                                     "is not recognised"),
            "missing provenance": ("draft", {}, lambda folder: (folder / "manifest.json").write_text(
                json.dumps({"outcome": "draft"})), "lacks the recorded provenance fields"),
            "response kept for a failure": ("technical-failure", {"response": decline_bytes}, None, "disagree"),
            "credential-like source": ("draft", {"body": with_source("key sk-ant-api03-abcdefghijkl")}, None,
                                       "credential-like"),
            "response ID differs": ("draft", {}, lambda folder: rewrite_manifest(folder, response={
                **json.loads((folder / "manifest.json").read_text())["response"], "id": "msg_other"}),
                "response ID does not match"),
        }
        good = self.attempt("draft", "good")
        for name, (kind, options, tamper, pattern) in tampers.items():
            with self.subTest(name):
                folder = self.attempt(kind, name.replace(" ", "-").replace(",", ""), **options)
                if tamper is not None:
                    tamper(folder)
                if kind == "technical-failure" and "response" in options:
                    rewrite_manifest(folder, response=None)
                with self.assertRaisesRegex(ProvenanceError, f"{pattern}.*nothing was prepared"):
                    self.prepare(good, folder)
                self.assertFalse(self.out.exists())  # Nothing is written when any selected attempt fails.
        with self.assertRaisesRegex(ValueError, "selected twice"):
            self.prepare(good, good)
        self.assertFalse(self.out.exists())

    def test_preparation_only_reads_attempts_and_never_writes_inside_pilot_records(self):
        attempts = [self.attempt(kind) for kind in ("draft", "no-draft", "invalid", "technical-failure")]
        before = files(self.pilot)
        for inside in (self.pilot, self.pilot / "views", attempts[0], attempts[1] / "views"):
            with self.subTest(out=str(inside.relative_to(self.root))):
                with self.assertRaisesRegex(ValueError, "inside saved pilot records"):
                    prepare_drafts(attempts, inside, self.pilot)
        self.prepare(*attempts)
        self.assertEqual(files(self.pilot), before)  # Byte-identical, and nothing was added.
        with self.assertRaisesRegex(ValueError, "at least one"):
            prepare_drafts([], self.out, self.pilot)

    def test_attempts_written_by_the_real_pilot_runner_prepare(self):
        from test_draft_pilot import CLOCK, FakeProvider, sonnet
        from second_order.draft_pilot import plan, send_case
        decline = {"type": "text", "text": "The source does not support a hypothesis."}
        runs = {"conflicting-labor-inflation": (FakeProvider(), "draft"),
                "ambiguous-wording": (FakeProvider(sonnet(content=[decline], stop_reason="end_turn")), "no_draft"),
                "headline-reports-move": (FakeProvider(b"{}", status=529), "technical_failure")}
        with patch("socket.socket.connect", side_effect=AssertionError("network attempted")):
            for case, (fake, _) in runs.items():
                send_case(case, "sk-ant-synthetic-test-key-0000000000", plan(case, lambda: CLOCK)[3], self.pilot,
                          fake.factory, lambda: CLOCK)
        index = self.prepare(*(self.pilot / case for case in runs))
        for row in index["drafts"]:
            view = self.view(index, row["case"])
            case = plan(row["case"], lambda: CLOCK)[0]
            self.assertEqual(view["outcome"], runs[row["case"]][1])
            self.assertEqual((view["source"]["headline"], view["source"]["text"]),
                             (case["operator"]["headline"], case["source_text"]))
            self.assertNotIn("sk-ant-synthetic-test-key", json.dumps(view))

    def test_views_match_the_captures_the_frontend_tests_read(self):
        kinds = ("draft", "no-draft", "invalid", "technical-failure")
        index = self.prepare(*(self.attempt(kind) for kind in kinds))
        captured = {"drafts-index.json": index}
        for row in index["drafts"]:
            captured[f"draft-{row['case']}.json"] = self.view(index, row["case"])
        for name, view in captured.items():
            text = json.dumps(view, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
            if os.environ.get(WRITE_FIXTURES) == "1":
                FRONTEND_FIXTURES.mkdir(parents=True, exist_ok=True)
                (FRONTEND_FIXTURES / name).write_bytes(text.encode("utf-8"))
            else:
                committed = json.loads((FRONTEND_FIXTURES / name).read_text(encoding="utf-8"))
                self.assertEqual(view, committed, f"frontend/tests/fixtures/{name} is stale; regenerate it with "
                                                  f"{WRITE_FIXTURES}=1 python -m unittest discover -s tests "
                                                  "-p test_draft_views.py")


class DraftApiAndCliTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.attempts = [write_attempt(self.root / "pilot" / kind, kind, kind)
                         for kind in ("draft", "no-draft", "invalid", "technical-failure")]
        self.out = self.root / "prepared-drafts"
        self.index = prepare_drafts(self.attempts, self.out, self.root / "pilot")

    def test_drafts_are_served_read_only_even_without_prepared_dossiers(self):
        with TestClient(create_app(self.root / "no-dossiers", None, self.out), base_url="http://127.0.0.1:8000") as client:
            self.assertEqual(client.get("/api/dossiers").status_code, 503)  # No Dossier index...
            listing = client.get("/api/drafts")  # ...and drafts still load.
            self.assertEqual((listing.status_code, listing.json()), (200, self.index))
            for row in self.index["drafts"]:
                response = client.get(f"/api/drafts/{row['id']}")
                self.assertEqual(response.content, (self.out / f"draft-{row['id']}.json").read_bytes())
            for draft_id in ("f" * 64, "not-an-id", "drafts-index", "%2E%2E", "draft-" + self.index["drafts"][0]["id"]):
                with self.subTest(draft_id=draft_id):
                    response = client.get(f"/api/drafts/{draft_id}")
                    self.assertEqual((response.status_code, response.json()["detail"]), (404, "Unknown draft ID"))
            self.assertEqual(client.post("/api/drafts").status_code, 405)
            self.assertEqual(client.delete(f"/api/drafts/{self.index['drafts'][0]['id']}").status_code, 405)

    def test_unprepared_drafts_explain_the_explicit_step_and_reads_never_prepare(self):
        with TestClient(create_app(self.root / "no-dossiers", None, self.root / "missing"),
                        base_url="http://127.0.0.1:8000") as client:
            for path in ("/api/drafts", f"/api/drafts/{self.index['drafts'][0]['id']}"):
                response = client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertIn("python -m second_order prepare-drafts", response.json()["detail"])
        before = files(self.out)
        forbidden = AssertionError("A read path must not prepare, rebuild or fetch")
        with TestClient(create_app(self.root / "no-dossiers", None, self.out), base_url="http://127.0.0.1:8000") as client, \
                patch("second_order.draft_views.build_view", side_effect=forbidden), \
                patch("second_order.draft_views.prepare_drafts", side_effect=forbidden), \
                patch("socket.socket.connect", side_effect=forbidden):
            for row in self.index["drafts"]:
                self.assertEqual(client.get(f"/api/drafts/{row['id']}").status_code, 200)
        self.assertEqual(files(self.out), before)

    def test_the_cli_prepares_selected_attempts_and_refuses_cleanly(self):
        out = self.root / "cli-drafts"
        common = [sys.executable, "-m", "second_order", "prepare-drafts", "--out", str(out)]
        run = subprocess.run(common + ["--attempt", str(self.attempts[0]), "--attempt", str(self.attempts[1])],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual([row["outcome"] for row in json.loads(run.stdout)["drafts"]], ["draft", "no_draft"])
        (self.attempts[2] / "request.json").write_bytes(b"{}")
        refused = subprocess.run(common + ["--attempt", str(self.attempts[2])], cwd=ROOT, capture_output=True,
                                 text=True, encoding="utf-8", timeout=60)
        self.assertEqual((refused.returncode, refused.stdout), (1, ""))
        self.assertIn("Failed: invalid: request.json does not match the recorded prompt hash", refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)


class BuildViewTests(unittest.TestCase):
    def test_a_view_is_built_from_records_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt = write_attempt(Path(folder) / "draft", "draft")
            with patch("second_order.draft_review.load_cases", side_effect=AssertionError("fixtures read")), \
                    patch("second_order.model_draft.build_request", side_effect=AssertionError("prompt rebuilt")):
                self.assertEqual(build_view(attempt)["outcome"], "draft")  # No fixture or prompt builder used.


if __name__ == "__main__":
    unittest.main()

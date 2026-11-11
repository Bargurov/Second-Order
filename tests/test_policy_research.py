"""Source-grounded research views (policy_research, research_api).

Three input layers stay apart. The committed research file is checked as content only (no retained source is read).
Mechanics run on SYNTHETIC sources and a SYNTHETIC research file (tests/policy_research_fakes.py) written into temporary
folders. One opt-in test (SECOND_ORDER_POLICY_RESEARCH_SOURCES=<the retained data/sector-sources folder>) checks the
committed file against the real retained snapshot and release pages, read-only, and proves nothing there changed.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import policy_research_fakes as fakes
from second_order import bis_snapshot, event_inbox, headline_triage, policy_research
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
REAL_SOURCES = "SECOND_ORDER_POLICY_RESEARCH_SOURCES"  # Explicit opt-in: the retained data/sector-sources folder.
BASE = "http://127.0.0.1:8137"
REAL_ID = "semiconductor-policy"
PACKAGE_SHA256 = "6209b876f4484c0614d363ff77a66de0c99b285fdf00f26ff49e7b6f8c910c4f"


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


def writable_rmtree(path: Path) -> None:
    shutil.rmtree(path, onexc=lambda remove, target, _: (os.chmod(target, stat.S_IWRITE), remove(target)))


def quotes_of(research: dict) -> list[tuple[str, int, str]]:
    """Every quoted passage of a research file: (publication id, paragraph, quote)."""
    found = []
    for item in research["publications"]:
        for dimension in item["dimensions"].values():
            for statement in dimension["statements"]:
                found += [(item["id"], excerpt["paragraph"], excerpt["quote"]) for excerpt in statement["excerpts"]]
        for reference in item["references"]:
            found += [(item["id"], excerpt["paragraph"], excerpt["quote"]) for excerpt in reference["excerpts"]]
    for comparison in research["comparisons"]:
        found += [(evidence["publication"], evidence["paragraph"], evidence["quote"])
                  for evidence in comparison["evidence"] if evidence["quote"] is not None]
    return found


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-policy-research-"))
        self.addCleanup(writable_rmtree, self.root)
        self.sources = fakes.write_sources(self.root / "sources")
        self.body = fakes.research(self.sources)
        self.content = fakes.write_research(self.root / "content", self.body)
        policy_research._MEMO.clear()  # Each test starts as a fresh process would.

    def view(self, body: dict | None = None, sources: dict | None = None) -> dict:
        if body is not None:
            fakes.write_research(self.content, body)
        return policy_research.view(fakes.RESEARCH_ID, self.content, sources or self.sources)

    def app(self) -> TestClient:
        return TestClient(create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                     self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                     triage=self.root / "triage", links=self.root / "links",
                                     market=self.root / "market", related_records=self.root / "related",
                                     related_sources=self.sources["related-cases-sources-01"],
                                     enrichment_sources=self.root / "es",
                                     snapshot_sources=self.sources["bis-semis-sources-01"],
                                     snapshot_index=self.root / "index", research=self.content), base_url=BASE)


# ---------------------------------------------------------------- the committed file, as content

class CommittedContentTests(unittest.TestCase):
    def test_the_committed_research_is_valid_and_bound_to_the_retained_versions(self):
        research = policy_research.load(REAL_ID)
        self.assertEqual(research["snapshot"]["sha256"], PACKAGE_SHA256)
        self.assertEqual(research["snapshot"]["extractor_version"], bis_snapshot.EXTRACTOR_VERSION)
        self.assertEqual(len(research["publications"]), 10)
        self.assertEqual(len(research["comparisons"]), 7)
        self.assertEqual(len({item["url"] for item in research["publications"]}), 10)
        self.assertEqual({page["dateline"] for page in research["release_pages"]},
                         {"October 7, 2022", "February 12, 2026"})
        for comparison in research["comparisons"]:
            self.assertTrue(comparison["unknown"] and comparison["would_establish"], comparison["id"])
        for _, _, quote in quotes_of(research):  # Quoted wording carries no markup, heading or table tokens.
            self.assertFalse(quote.startswith("#") or "|" in quote or "<" in quote or "\n" in quote, quote)
        # The January 2026 release keeps both of its differing fields; neither is presented as its dateline.
        january = next(item for item in research["publications"] if item["id"] == "license-review-2026")
        self.assertEqual((january["listing"]["published"], january["listing"]["created"], january["release_page"]),
                         ("2026-01-13T23:00:00+00:00", "2026-01-14T13:27:12+00:00", None))
        dates = next(item for item in research["comparisons"] if item["id"] == "which-date")
        self.assertIn("remains unresolved", dates["unknown"])

    def test_curator_text_keeps_to_what_the_project_claims(self):
        research = policy_research.load(REAL_ID)
        texts = [research[field] for field in ("title", "question", "scope_note", "method_note")]
        texts += research["corpus_notes"] + [item["reason"] for item in research["not_included"]]
        for item in research["publications"]:
            texts += [item["short_title"], item["why_included"]]
            for dimension in item["dimensions"].values():
                texts += [dimension["label"]] + [statement["text"] for statement in dimension["statements"]]
        for comparison in research["comparisons"]:
            texts += [comparison[field] for field in ("question", "observation", "why", "unknown", "would_establish")]
        for text in texts:
            self.assertIsNone(policy_research.BANNED.search(text), text)
        self.assertTrue(any(policy_research.BANNED.search(claim) for claim in research["not_claimed"]))

    def test_without_retained_sources_nothing_is_shown_as_checked(self):
        with tempfile.TemporaryDirectory() as empty:
            sources = {"bis-semis-sources-01": Path(empty) / "bis", "related-cases-sources-01": Path(empty) / "rc"}
            view = policy_research.view(REAL_ID, sources=sources)
        self.assertEqual(view["snapshot"]["state"], "missing")
        self.assertIsNone(view["snapshot"]["filter_matches"])
        self.assertEqual(view["counts"], {"publications": {"verified": 0, "changed": 0, "missing": 10},
                                          "comparisons": {"available": 0, "needs_revalidation": 0, "unavailable": 7}})
        for item in view["publications"]:
            self.assertEqual((item["dimensions"], item["stages"], item["references"]), (None, None, None))
            self.assertEqual(item["text"]["status"], "listing_text")
            if item["dateline"]:
                self.assertEqual((item["dateline"]["state"], item["dateline"]["value"]), ("missing", None))
        for comparison in view["comparisons"]:
            self.assertEqual([comparison[field] for field in ("observation", "evidence", "why", "unknown")],
                             [None] * 4)
            self.assertTrue(comparison["problems"])
        self.assertEqual({page["state"] for page in view["release_pages"]}, {"missing"})

    def test_unknown_and_malformed_ids_are_not_found(self):
        for research_id in ("no-such-view", "../content", "Semiconductor-Policy", "", "a/b"):
            with self.assertRaises(policy_research.PolicyRefused) as refused:
                policy_research.load(research_id)
            self.assertEqual(refused.exception.status, 404, research_id)


# ---------------------------------------------------------------- strict content checks

class RefusalTests(Folders):
    def refused(self, change) -> str:
        fakes.write_research(self.content, fakes.changed(self.body, change))
        with self.assertRaises(policy_research.PolicyRefused) as refused:
            policy_research.load(fakes.RESEARCH_ID, self.content)
        self.assertEqual(refused.exception.status, 500)
        return str(refused.exception)

    def statement(self, body, publication, dimension, index=0):
        item = next(item for item in body["publications"] if item["id"] == publication)
        return item["dimensions"][dimension]["statements"][index]

    def test_every_dimension_must_be_given_and_none_is_defaulted(self):
        self.refused(lambda b: b["publications"][1]["dimensions"].pop("parties"))
        self.refused(lambda b: b["publications"][1]["dimensions"]["parties"].update(statements=[]))
        self.refused(lambda b: self.statement(b, "synthetic-update", "parties").update(
            excerpts=[{"paragraph": 1, "quote": "this rule modifies the rule"}]))  # Silence quotes nothing.
        self.refused(lambda b: self.statement(b, "synthetic-update", "scope").update(excerpts=[]))

    def test_statements_and_interpretation_stay_apart(self):
        self.refused(lambda b: self.statement(b, "synthetic-update", "supply_chain").update(status="stated"))
        self.refused(lambda b: self.statement(b, "synthetic-update", "supply_chain").update(stage="logistics"))
        self.refused(lambda b: self.statement(b, "synthetic-update", "scope").update(stage="equipment"))
        self.refused(lambda b: self.statement(b, "synthetic-update", "supply_chain").update(excerpts=[]))
        self.refused(lambda b: self.statement(b, "synthetic-rule", "conditions").update(reference="no-such-document"))
        self.refused(lambda b: self.statement(b, "synthetic-rule", "scope").update(reference="synthetic-rule-text"))

    def test_figures_must_come_from_the_cited_passages(self):
        self.refused(lambda b: self.statement(b, "synthetic-update", "scope").update(text="It removes 2 parameters."))
        self.refused(lambda b: b["publications"][1]["dimensions"]["scope"].update(label="Seven parameters, 7 tools"))
        self.refused(lambda b: b["comparisons"][0].update(observation="The update modifies the 2025 rule."))
        self.refused(lambda b: b["comparisons"][0].update(why="It states the relationship in 2 places."))

    def test_claims_the_project_does_not_make_are_refused_outside_their_list(self):
        message = self.refused(lambda b: b["comparisons"][0].update(observation="This confirms the update."))
        self.assertIn("confirms", message)
        self.refused(lambda b: b["comparisons"][1].update(why="The second release caused the first."))
        self.refused(lambda b: b["publications"][0].update(why_included="A buy case."))
        fakes.write_research(self.content, self.body)
        policy_research.load(fakes.RESEARCH_ID, self.content)  # The unchanged file, whose not_claimed says "caused".

    def test_dates_keep_their_stated_value_and_precision(self):
        def timing(b, index=0):
            return self.statement(b, "synthetic-rule", "timing", index)["dates"][0]
        self.refused(lambda b: timing(b).update(value="2026-03-03"))
        self.refused(lambda b: timing(b).update(precision="year"))
        self.refused(lambda b: timing(b, 1).update(value="2026-02-01"))  # A relative date has no calendar value.
        self.refused(lambda b: timing(b).update(as_stated="March 3, 2026"))  # Not quoted.
        self.refused(lambda b: timing(b).update(kind="announced"))
        self.refused(lambda b: self.statement(b, "synthetic-rule", "scope").update(dates=[timing(b)]))

    def test_identity_order_and_bindings_are_strict(self):
        self.refused(lambda b: b["publications"].append(dict(b["publications"][0], id="synthetic-copy")))
        self.refused(lambda b: b["publications"][1]["record"].update(key="0" * 20))
        self.refused(lambda b: b["publications"].reverse())
        self.refused(lambda b: b["publications"][0].update(url="https://example.invalid/press-release/x"))
        self.refused(lambda b: b["publications"][0].update(release_page="no-such-page"))
        self.refused(lambda b: b["publications"][1].update(release_page="synthetic-rule-page"))  # Another address.
        self.refused(lambda b: b["comparisons"][0]["evidence"].append(
            fakes.evidence("synthetic-first", 1, "Synthetic first document")))
        self.refused(lambda b: b["comparisons"][0].update(evidence=b["comparisons"][0]["evidence"][:2]))
        self.refused(lambda b: b["comparisons"][0]["evidence"][0].update(field="published"))
        self.refused(lambda b: b["comparisons"][0]["evidence"][1].update(value="2026-01-11T15:00:00+00:00"))
        self.refused(lambda b: b["comparisons"][0]["evidence"][0].update(quote="Synthetic <b>bold</b> text"))
        self.refused(lambda b: b["not_included"][0].update(key=b["publications"][0]["record"]["key"]))
        self.refused(lambda b: b["provenance"].update(human_review="reviewed"))
        self.refused(lambda b: b.update(extra=True))
        self.refused(lambda b: b.update(research_version="policy-research-0.2"))

    def test_a_file_that_is_not_strict_json_is_refused(self):
        path = self.content / fakes.RESEARCH_ID / "research.json"
        path.write_text('{"id": "a", "id": "b"}', encoding="utf-8")
        with self.assertRaises(policy_research.PolicyRefused) as refused:
            policy_research.load(fakes.RESEARCH_ID, self.content)
        self.assertEqual(refused.exception.status, 500)

    def test_a_link_to_a_case_the_library_does_not_hold_refuses_the_view(self):
        body = fakes.changed(self.body, lambda b: b["publications"][0]["cases"][0].update(id="no-such-case"))
        with self.assertRaises(policy_research.PolicyRefused) as refused:
            self.view(body)
        self.assertEqual(refused.exception.status, 500)


# ---------------------------------------------------------------- reading against the retained sources

class ViewTests(Folders):
    def test_every_binding_checks_and_every_comparison_is_available(self):
        view = self.view()
        self.assertEqual((view["view_version"], view["provider_called"]), (policy_research.VIEW_VERSION, False))
        self.assertEqual(view["snapshot"]["state"], "verified")
        self.assertEqual(view["counts"], {"publications": {"verified": 4, "changed": 0, "missing": 0},
                                          "comparisons": {"available": 2, "needs_revalidation": 0, "unavailable": 0}})
        index = bis_snapshot.build(self.sources["bis-semis-sources-01"])
        records = {record["key"]: record for record in index["records"]}
        self.assertEqual(view["snapshot"]["filter_matches"],
                         sum(record["filters"]["semiconductors"]["matched"] for record in index["records"]))
        by_id = {item["id"]: item for item in self.body["publications"]}
        for publication, paragraph, quote in quotes_of(self.body):  # Excerpt fidelity, checked independently.
            text = records[by_id[publication]["record"]["key"]]["text"]["paragraphs"]
            self.assertIn(quote, text[paragraph - 1])
        evidence = view["comparisons"][0]["evidence"]
        self.assertEqual([item["kind"] for item in evidence], ["quote", "field", "quote"])
        self.assertEqual((evidence[0]["paragraph"], evidence[0]["paragraphs"]), (1, 5))
        self.assertEqual(view["comparisons"][1]["evidence"][2]["kind"], "absence")
        rule = view["publications"][0]
        self.assertEqual((rule["text"]["status"], rule["dateline"]["value"], rule["dateline"]["state"]),
                         ("checked", "January 10, 2026", "verified"))
        self.assertEqual(rule["cases"][0]["href"], "/library/historical/bis-2022-10-07")
        self.assertEqual(rule["stages"], ["chips"])
        self.assertEqual(view["not_included"][0]["state"], "verified")
        self.assertEqual(view["not_included"][0]["case"]["href"], "/library/bis-2026-07-10")

    def test_documents_with_the_same_title_stay_separate(self):
        view = self.view()
        first, second = view["publications"][2:]
        self.assertEqual(first["title"], second["title"])
        self.assertNotEqual((first["url"], first["record"]["key"]), (second["url"], second["record"]["key"]))
        self.assertEqual((first["state"], second["state"]), ("verified", "verified"))
        self.assertEqual(view["comparisons"][1]["state"], "available")

    def test_dates_keep_their_fields_and_nothing_is_filled_in(self):
        view = self.view()
        rule, update = view["publications"][:2]
        self.assertNotEqual(rule["listing"]["published"], rule["listing"]["created"])
        dates = [date for statement in rule["dimensions"]["timing"]["statements"] for date in statement["dates"]]
        self.assertEqual([(date["precision"], date["value"]) for date in dates],
                         [("day", "2026-03-02"), ("relative", None)])
        self.assertIsNone(update["dateline"])  # No release page: no dateline, never one taken from the listing.
        silent = update["dimensions"]["timing"]["statements"]
        self.assertEqual([(item["status"], item["excerpts"], item["dates"]) for item in silent],
                         [("not_stated", [], [])])
        self.assertEqual(view["labels"]["statuses"]["not_stated"], "Not stated in this source")

    def test_a_changed_snapshot_needs_revalidation(self):
        fakes.write_sources(self.root / "sources", update_body="<p>Synthetic: a different text.</p>")
        view = self.view()
        self.assertEqual(view["snapshot"]["state"], "changed")
        self.assertEqual(view["counts"]["comparisons"], {"available": 0, "needs_revalidation": 2, "unavailable": 0})
        self.assertTrue(all(item["state"] == "changed" and item["dimensions"] is None for item in view["publications"]))
        self.assertTrue(all(item["observation"] is None for item in view["comparisons"]))

    def test_retained_bytes_that_differ_from_their_record_need_revalidation(self):
        page = self.sources["bis-semis-sources-01"] / "news-updates" / "source.html"
        page.write_bytes(page.read_bytes().replace(b"Synthetic second", b"Synthetic SECOND"))
        view = self.view()
        self.assertEqual((view["snapshot"]["state"], view["counts"]["publications"]["changed"]), ("changed", 4))

    def test_a_missing_snapshot_makes_every_comparison_unavailable(self):
        writable_rmtree(self.sources["bis-semis-sources-01"])
        view = self.view()
        self.assertEqual(view["snapshot"]["state"], "missing")
        self.assertEqual(view["counts"]["comparisons"], {"available": 0, "needs_revalidation": 0, "unavailable": 2})

    def test_a_record_written_against_another_version_needs_revalidation(self):
        body = fakes.changed(self.body, lambda b: b["publications"][1]["record"].update(record_sha256="0" * 64))
        view = self.view(body)
        states = {item["id"]: item["state"] for item in view["publications"]}
        self.assertEqual(states, {"synthetic-rule": "verified", "synthetic-update": "changed",
                                  "synthetic-first": "verified", "synthetic-second": "verified"})
        self.assertIn("differs from the version", view["publications"][1]["problems"][0])
        self.assertEqual([item["state"] for item in view["comparisons"]], ["needs_revalidation", "available"])
        self.assertIsNone(view["comparisons"][0]["evidence"])

    def test_a_quote_no_longer_found_needs_revalidation(self):
        body = fakes.changed(self.body, lambda b: b["publications"][1]["dimensions"]["scope"]["statements"][0].update(
            excerpts=[{"paragraph": 2, "quote": "it removes two parameters"}]))
        view = self.view(body)
        self.assertEqual(view["publications"][1]["state"], "changed")
        self.assertIn("Paragraph 2 no longer holds", view["publications"][1]["problems"][0])
        self.assertEqual(view["comparisons"][0]["state"], "needs_revalidation")

    def test_a_term_reported_absent_that_appears_needs_revalidation(self):
        body = fakes.changed(self.body, lambda b: b["comparisons"][1]["evidence"][2].update(absent="different"))
        view = self.view(body)
        self.assertEqual([item["state"] for item in view["comparisons"]], ["available", "needs_revalidation"])
        self.assertIn("“different”", view["comparisons"][1]["problems"][0])

    def test_a_missing_or_changed_release_page_only_withholds_its_dateline(self):
        related = self.sources["related-cases-sources-01"]
        (related / fakes.PAGE_FOLDER / "source.html").unlink()
        view = self.view()
        rule = view["publications"][0]
        self.assertEqual((rule["state"], rule["dateline"]["state"], rule["dateline"]["value"], rule["text"]["status"]),
                         ("verified", "missing", None, "listing_text"))
        self.assertEqual(view["comparisons"][0]["state"], "available")
        (related / fakes.PAGE_FOLDER / "source.html").write_bytes(fakes.release_page() + b" ")
        view = self.view()
        self.assertEqual((view["release_pages"][0]["state"], view["publications"][0]["dateline"]["value"]),
                         ("changed", None))

    def test_a_release_page_with_another_dateline_is_not_used(self):
        fakes.write_sources(self.root / "sources", page=fakes.fakes.release_page(
            fakes.RULE_TITLE, "January 11, 2026", fakes.RULE_BODY))
        body = fakes.changed(self.body, lambda b: b["release_pages"][0].update(
            sha256=hashlib.sha256(fakes.fakes.release_page(fakes.RULE_TITLE, "January 11, 2026",
                                                           fakes.RULE_BODY)).hexdigest()))
        view = self.view(body)
        self.assertEqual((view["release_pages"][0]["state"], view["publications"][0]["dateline"]["value"]),
                         ("changed", None))


class ApiTests(Folders):
    def test_reading_writes_nothing_and_makes_no_outside_request_or_model_call(self):
        calls = []
        connect = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                calls.append(("connect", address))
                raise AssertionError("an outside connection was attempted")
            return connect(sock, address)

        def counted(name):
            def call(*args, **kwargs):
                calls.append((name, None))
                raise AssertionError(f"{name} was called")
            return call
        watched = [self.root, ROOT / "content", ROOT / "frontend" / "tests" / "fixtures"]
        before = [tree(folder) for folder in watched]
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo", counted("name lookup")), \
                patch.object(event_inbox.FeedFetcher, "fetch", counted("feed fetch")), \
                patch.object(headline_triage, "build_request", counted("model request")), \
                patch("second_order.triage_flow.dispatch", counted("triage dispatch")):
            with self.app() as client:  # Startup runs; nothing is built or read until the page asks.
                self.assertEqual(policy_research._MEMO, {})
                first = client.get(f"/api/research/{fakes.RESEARCH_ID}")
                again = client.get(f"/api/research/{fakes.RESEARCH_ID}")
            policy_research._MEMO.clear()
            with self.app() as client:  # A restart reads and checks again; it does not regenerate anything.
                restarted = client.get(f"/api/research/{fakes.RESEARCH_ID}")
        self.assertEqual(calls, [])
        self.assertEqual((first.status_code, again.status_code, restarted.status_code), (200, 200, 200))
        self.assertEqual(first.json(), restarted.json())
        self.assertEqual([tree(folder) for folder in watched], before)
        self.assertFalse((self.root / "inbox").exists())

    def test_the_catalog_lists_views_from_content_alone(self):
        writable_rmtree(self.sources["bis-semis-sources-01"])  # No retained source is needed to list the views.
        with self.app() as client:
            catalog = client.get("/api/research").json()
        self.assertEqual((catalog["view_version"], catalog["provider_called"]), (policy_research.CATALOG_VERSION, False))
        self.assertEqual([(view["id"], view["publications"], view["comparisons"], view["href"])
                          for view in catalog["views"]],
                         [(fakes.RESEARCH_ID, 4, 2, f"/library/research/{fakes.RESEARCH_ID}")])
        self.assertEqual([view["id"] for view in policy_research.catalog()["views"]], [REAL_ID])

    def test_the_route_reads_only(self):
        with self.app() as client:
            self.assertEqual(client.get(f"/api/research/{fakes.RESEARCH_ID}").json()["counts"]["comparisons"]
                             ["available"], 2)
            self.assertEqual(client.get("/api/research/no-such-view").status_code, 404)
            self.assertEqual(client.get("/api/research/Bad_Id").status_code, 404)
            self.assertEqual(client.post(f"/api/research/{fakes.RESEARCH_ID}", json={}).status_code, 405)
        # The research views' own routes; /api/research-analyses (research_analysis) is another feature.
        routes = [route for route in self.app().app.routes
                  if getattr(route, "path", "") == "/api/research" or getattr(route, "path", "").startswith("/api/research/")]
        self.assertEqual([(route.path, route.methods) for route in routes],
                         [("/api/research", {"GET"}), ("/api/research/{research_id}", {"GET"})])

    def test_served_views_match_the_committed_frontend_fixtures(self):
        revalidation = fakes.changed(self.body, lambda b: b["publications"][1]["record"].update(record_sha256="0" * 64))
        with self.app() as client:
            served = {"policy-research-available.json": client.get(f"/api/research/{fakes.RESEARCH_ID}").json(),
                      "policy-research-catalog.json": client.get("/api/research").json()}
            fakes.write_research(self.content, revalidation)
            served["policy-research-revalidation.json"] = client.get(f"/api/research/{fakes.RESEARCH_ID}").json()
        with tempfile.TemporaryDirectory() as empty:  # The committed file on a machine without the retained sources.
            served["policy-research-unavailable.json"] = policy_research.view(
                REAL_ID, sources={"bis-semis-sources-01": Path(empty), "related-cases-sources-01": Path(empty)})
        for name, body in served.items():
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))
            else:
                self.assertEqual(body, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_policy_research.py")


@unittest.skipUnless(os.environ.get(REAL_SOURCES), f"opt-in: set {REAL_SOURCES} to the retained data/sector-sources "
                                                   "folder")
class RetainedSourcesTests(unittest.TestCase):
    """The committed research file against the real retained snapshot and release pages. Read-only."""

    def test_every_publication_and_comparison_checks_against_the_retained_sources(self):
        folder = Path(os.environ[REAL_SOURCES])
        self.assertTrue((folder / "bis").is_dir() and (folder / "related-cases").is_dir(),
                        f"{REAL_SOURCES} must name the folder holding bis/ and related-cases/")
        sources = {"bis-semis-sources-01": folder / "bis", "related-cases-sources-01": folder / "related-cases"}
        before = tree(folder)
        policy_research._MEMO.clear()
        view = policy_research.view(REAL_ID, sources=sources)
        self.assertEqual(view["counts"], {"publications": {"verified": 10, "changed": 0, "missing": 0},
                                          "comparisons": {"available": 7, "needs_revalidation": 0, "unavailable": 0}})
        self.assertEqual((view["snapshot"]["state"], view["snapshot"]["filter_matches"]), ("verified", 65))
        self.assertEqual({page["id"]: page["state"] for page in view["release_pages"]},
                         {"bis-2022-10-07-page": "verified", "bis-2026-02-12-page": "verified"})
        self.assertEqual([(item["id"], item["text"]["status"]) for item in view["publications"]
                          if item["text"]["status"] == "checked"],
                         [("ac-sme-rules-2022", "checked"), ("applied-penalty-2026", "checked")])
        self.assertTrue(all(item["state"] == "verified" for item in view["not_included"]))
        # Excerpt fidelity, checked here independently of the module.
        research = policy_research.load(REAL_ID)
        records = {record["key"]: record for record in bis_snapshot.build(sources["bis-semis-sources-01"])["records"]}
        by_id = {item["id"]: item for item in research["publications"]}
        for publication, paragraph, quote in quotes_of(research):
            self.assertIn(quote, records[by_id[publication]["record"]["key"]]["text"]["paragraphs"][paragraph - 1])
        for item in research["publications"]:
            listing = records[item["record"]["key"]]["listing"]
            self.assertEqual({field: listing[field]["time"] for field in ("published", "created", "changed")},
                             item["listing"])
        january = next(item for item in view["publications"] if item["id"] == "license-review-2026")
        self.assertIsNone(january["dateline"])
        self.assertEqual(tree(folder), before)


if __name__ == "__main__":
    unittest.main()

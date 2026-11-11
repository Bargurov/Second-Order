"""The private event overview: one event's source, saved triage, draft and review, and market context, joined only by
stable IDs and explicit, verified links; read from local records without fetching, writing or approving anything.

SYNTHETIC feeds, model replies and Board replies, through counting fakes (an httpx MockTransport each), in temporary
folders. Nothing reaches a network, reads a key or touches data/.
"""
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import stat
from unittest.mock import patch

from fastapi.testclient import TestClient

from market_fakes import Clock, FakeRelease
from test_event_inbox import BASE, Network, fingerprint, rss, rss_item
from test_headline_triage import FED_LINK, NOTE, STATEMENT, Provider, Triage, feeds, rich_reply
from test_triage_quality import Recheck
from second_order import event_inbox, headline_triage, human_review, market_retrieval
from second_order.api import create_app
from second_order.event_context import CONVENTION
from test_event_inbox import FED, QUIET

INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
REVIEW = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Review": "1"}
CONTEXT = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Context": "1"}
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)


class Overview(Triage):
    """The triage fixture's inbox (a recurring FOMC title on two dates, a note, jobs and prices), plus the Tracker's
    folders, market context and links, behind an app whose every outward transport is a counting fake."""

    def setUp(self):
        super().setUp()
        self.feeds = Network({})  # Any feed request would be recorded here (and refused).
        self.board = FakeRelease(Clock(NOW))
        self.provider = Provider(rich_reply)
        self.clock = Clock(NOW)
        self.client = TestClient(self.app(), base_url=BASE)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def app(self):
        return create_app(self.root / "prepared", None, self.root / "prepared-drafts", self.root / "reviews",
                          self.root / "intake", self.root / "attempts", inbox=self.inbox, feeds=self.feeds.fetcher(),
                          triage=self.triage, triage_senders=self.provider.senders(paid=True),
                          market=self.root / "market", market_fetcher=self.board.fetcher(), market_clock=self.clock,
                          context=self.root / "no-bundle", links=self.root / "links")

    def item(self, item_id: str) -> dict:
        view = event_inbox.inbox_view(self.inbox)
        return next(item for item in view["items"] + view["retained"] if item["id"] == item_id)

    def capture(self, headline: str, link: str, origin: str | None = None, published_at: str = "2026-09-16T14:00:00-04:00",
                version: str | None = None, status: int = 201) -> dict:
        form = {"headline": headline, "source_url": link, "published_at": published_at,
                "source_text": f"Synthetic published text for {headline}."}
        if origin:
            form["origin"] = {"item_id": origin, "content_sha256": version or self.item(origin)["content_sha256"]}
        response = self.client.post("/api/intake", content=json.dumps(form), headers=INTAKE)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def mock(self, preview: dict, outcome: str = "draft") -> str:
        body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": outcome})
        response = self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", content=body, headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["draft_id"]

    def review(self, draft_id: str, status: str | None, notes: str, parent: str | None = None) -> dict:
        loaded = self.client.get(f"/api/drafts/{draft_id}")
        provenance = loaded.json()["provenance"]
        body = {"parent_review_id": parent, "status": status, "notes": notes, "corrections": {"summary": None, "legs": {}},
                "binding": {"draft_view_sha256": loaded.headers["x-draft-view-sha256"],
                            "prompt_hash": provenance["prompt_hash"], "response_sha256": provenance["response_sha256"]}}
        saved = self.client.post(f"/api/drafts/{draft_id}/reviews", content=json.dumps(body), headers=REVIEW)
        self.assertEqual(saved.status_code, 201, saved.text)
        return saved.json()

    def overview(self, kind: str, event_id: str, status: int = 200) -> dict:
        response = self.client.get(f"/api/events/{kind}/{event_id}")
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def no_calls(self):
        self.assertEqual((len(self.feeds.requests), len(self.board.calls), len(self.provider.requests)), (0, 0, 0))


class SourceAndLinkTests(Overview):
    def test_an_inbox_only_entry_shows_its_feed_metadata_and_empty_sections(self):
        statement = self.id(STATEMENT, "0916a")
        page = self.overview("inbox", statement)
        self.assertEqual((page["overview_version"], page["kind"], page["provider_called"]), ("event-overview-0.1", "inbox",
                                                                                               False))
        self.assertIn("not a research Dossier", page["not_a_dossier"])
        source = page["source"]
        self.assertEqual((source["entry"]["title"], source["entry"]["link"], source["location"]),
                         (STATEMENT, FED_LINK.format("20260916a"), "current"))
        self.assertEqual(len(source["versions"]), 1)
        self.assertTrue(source["versions"][0]["current"])
        self.assertIn("not a verified publication instant", source["note"])
        self.assertEqual((page["triage"]["state"], page["analysis"]["state"], page["market"]["state"]),
                         ("none", "none", "needs_date"))
        self.no_calls()

    def test_a_capture_only_event_keeps_its_supplied_time_and_shows_no_invented_origin(self):
        preview = self.capture(STATEMENT, "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm",
                               published_at="2025-09-17T14:00:00-04:00")
        page = self.overview("capture", preview["capture_id"])
        source = page["source"]
        self.assertEqual((source["times"]["published_at_as_supplied"], source["origin"]["state"]),
                         ("2025-09-17T14:00:00-04:00", "none"))
        self.assertEqual(source["source_text"], f"Synthetic published text for {STATEMENT}.")
        self.assertIn("not verified", source["note"])
        self.assertEqual((page["triage"]["state"], page["analysis"]["state"]), ("no_origin", "none"))
        self.assertEqual((page["market"]["state"], page["market"]["event"]["context"]["date"]), ("no_data", "2025-09-17"))
        self.no_calls()

    def test_a_capture_from_the_inbox_records_its_origin_beside_unchanged_request_bytes(self):
        statement = self.id(STATEMENT, "0916a")
        entry = self.item(statement)
        plain = self.capture(STATEMENT, entry["link"])
        linked = self.capture(STATEMENT, entry["link"], origin=statement)
        self.assertEqual(linked["request_sha256"], plain["request_sha256"])  # The origin is not part of the request.
        self.assertTrue(linked["origin"]["recorded"])
        self.assertNotIn("origin", plain)
        link_file = self.root / "links" / f"{linked['capture_id']}.json"
        record = json.loads(link_file.read_text(encoding="utf-8"))
        self.assertEqual((record["inbox"]["item_id"], record["inbox"]["content_sha256"], record["inbox"]["version"],
                          record["form"]), (statement, entry["content_sha256"], 1,
                                            {"headline_matches": True, "source_url_matches": True}))
        self.assertFalse(os.access(link_file, os.W_OK))
        self.assertFalse((self.root / "intake" / linked["capture_id"] / "origin.json").exists())
        inbox_page = self.overview("inbox", statement)
        self.assertEqual([row["capture_id"] for row in inbox_page["analysis"]["captures"]], [linked["capture_id"]])
        capture_page = self.overview("capture", linked["capture_id"])
        self.assertEqual((capture_page["source"]["origin"]["state"], capture_page["triage"]["state"]),
                         ("verified", "none"))
        self.assertEqual(self.overview("capture", plain["capture_id"])["triage"]["state"], "no_origin")

    def test_an_origin_that_is_not_held_at_that_version_captures_nothing(self):
        statement = self.id(STATEMENT, "0916a")
        before = fingerprint(self.root)
        for origin, version, status in ((statement, "0" * 64, 409), ("fed-monetary:0123456789abcdef0123", "0" * 64, 409),
                                        (statement, "not-a-hash", 422)):
            with self.subTest(origin=origin, version=version):
                self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=origin, version=version, status=status)
        self.assertEqual(fingerprint(self.root), before)

    def test_recurring_identical_titles_and_multiple_captures_stay_separate(self):
        september, july = self.id(STATEMENT, "0916a"), self.id(STATEMENT, "0729a")
        first = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=september)
        second = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=september)
        by_title = self.capture(STATEMENT, FED_LINK.format("20260729a"))  # Same title, no recorded origin.
        self.assertEqual([row["capture_id"] for row in self.overview("inbox", september)["analysis"]["captures"]],
                         [first["capture_id"], second["capture_id"]])
        self.assertEqual(self.overview("inbox", july)["analysis"]["captures"], [])
        siblings = self.overview("capture", first["capture_id"])["analysis"]["siblings"]
        self.assertEqual([row["capture_id"] for row in siblings], [second["capture_id"]])
        self.assertEqual(self.overview("capture", by_title["capture_id"])["source"]["origin"]["state"], "none")

    def test_a_changed_entry_keeps_earlier_links_triage_and_dates_on_their_own_version(self):
        statement = self.id(STATEMENT, "0916a")
        v1 = self.item(statement)
        self.process(statement, provider=self.provider)  # A simulated result for version 1.
        linked = self.capture(STATEMENT, v1["link"], origin=statement)
        body = {"context_date": "2026-09-16", "convention": CONVENTION["id"], "version": 1}
        self.assertEqual(self.client.post(f"/api/market-context/inbox/{statement}/confirm", json=body,
                                          headers=CONTEXT).status_code, 201)
        changed = feeds()
        changed[FED] = [(200, rss([rss_item(1, f"{STATEMENT} (title edited)", FED_LINK.format("20260916a"),
                                            pub="Wed, 16 Sep 2026 18:00:00 GMT",
                                            description="The Committee decided to maintain the target range for the "
                                                        "federal funds rate.")]))]
        self.refresh(changed, datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc))
        page = self.overview("inbox", statement)
        self.assertEqual([version["current"] for version in page["source"]["versions"]], [False, True])
        self.assertEqual((page["triage"]["state"], page["triage"]["modes"][0]["status"],
                          page["triage"]["modes"][0]["other_versions_with_results"]), ("results", "none", 1))
        self.assertIsNone(page["triage"]["modes"][0]["result"])  # Version 1's result is counted, never shown as version 2's.
        self.assertEqual(page["market"]["state"], "stale_confirmation")
        self.assertEqual(page["market"]["event"]["confirmation_stale"]["context_date"], "2026-09-16")
        (row,) = page["analysis"]["captures"]
        self.assertEqual((row["origin"]["state"], row["origin"]["entry"]["same_version_as_current"],
                          row["origin"]["entry"]["held"]), ("verified", False, True))
        capture_page = self.overview("capture", linked["capture_id"])
        self.assertEqual((capture_page["triage"]["state"], capture_page["triage"]["modes"][0]["status"]),
                         ("results", "current"))  # The capture started from version 1, which has its own result.
        # Confirming again binds the date to the version held now; version 1 of the confirmation stays.
        body["version"] = 2
        self.assertEqual(self.client.post(f"/api/market-context/inbox/{statement}/confirm", json=body,
                                          headers=CONTEXT).status_code, 201)
        self.assertEqual(self.overview("inbox", statement)["market"]["state"], "no_data")


class AnalysisTests(Overview):
    def test_a_reviewed_draft_shows_model_output_apart_from_the_current_review(self):
        preview = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=self.id(STATEMENT, "0916a"))
        draft_id = self.mock(preview)
        self.assertEqual(self.overview("capture", preview["capture_id"])["analysis"]["entry"]["review"]["state"], "none")
        served = self.client.get(f"/api/drafts/{draft_id}").headers["x-draft-view-sha256"]
        self.review(draft_id, "human_reviewed", "Checked against the source.")
        analysis = self.overview("capture", preview["capture_id"])["analysis"]
        entry = analysis["entry"]
        self.assertEqual((analysis["state"], entry["outcome"], entry["mode"], entry["model_output"]["kind"]),
                         ("listed", "draft", "mock", "summary"))
        self.assertEqual((entry["review"]["state"], entry["review"]["status"], entry["review"]["notes_excerpt"]),
                         ("current", "human_reviewed", "Checked against the source."))
        self.assertEqual(entry["draft_view_sha256"], served)
        # Reading the overview, market section included, changes neither the served view nor its review binding.
        self.assertEqual(self.client.get(f"/api/drafts/{draft_id}").headers["x-draft-view-sha256"], served)
        inbox_row = self.overview("inbox", self.id(STATEMENT, "0916a"))["analysis"]["captures"][0]
        self.assertEqual((inbox_row["analysis"]["outcome"], inbox_row["analysis"]["review"]["status"]),
                         ("draft", "human_reviewed"))

    def test_a_stale_or_unreadable_review_is_never_shown_as_current(self):
        preview = self.capture(STATEMENT, FED_LINK.format("20260916a"))
        draft_id = self.mock(preview)
        first = self.review(draft_id, "human_reviewed", "Reviewed.")
        stale = {**{key: first[key] for key in ("record_version", "draft_id", "attributed_to", "corrections")},
                 "sequence": 2, "parent_review_id": first["review_id"], "saved_at": "2026-10-08T12:00:00+00:00",
                 "status": "human_reviewed", "notes": "Saved against an earlier view.",
                 "binding": {**first["binding"], "draft_view_sha256": "0" * 64}}
        stale["review_id"] = human_review.review_id(stale)
        (self.root / "reviews" / draft_id / "000002.json").write_text(json.dumps(stale), encoding="utf-8")
        self.assertEqual(self.overview("capture", preview["capture_id"])["analysis"]["entry"]["review"]["state"], "stale")
        (self.root / "reviews" / draft_id / "000002.json").write_text("{not json", encoding="utf-8")
        review = self.overview("capture", preview["capture_id"])["analysis"]["entry"]["review"]
        self.assertEqual(review["state"], "invalid")
        self.assertIn("not strict JSON", review["problem"])

    def test_a_refusal_and_an_unfinished_attempt_are_shown_as_recorded(self):
        refusal = self.capture("Refusal event", FED_LINK.format("20260916a"))
        self.mock(refusal, "no_draft")
        entry = self.overview("capture", refusal["capture_id"])["analysis"]["entry"]
        self.assertEqual((entry["outcome"], entry["model_output"]["kind"]), ("no_draft", "explanation"))
        unfinished = self.capture("Unfinished event", FED_LINK.format("20260916a"))
        (self.root / "attempts" / unfinished["capture_id"]).mkdir(parents=True)
        (self.root / "attempts" / unfinished["capture_id"] / "reservation.json").write_text(
            json.dumps({"mode": "mock"}), encoding="utf-8")
        analysis = self.overview("capture", unfinished["capture_id"])["analysis"]
        self.assertEqual((analysis["state"], analysis["entry"]), ("incomplete", None))
        self.assertIn("did not finish", analysis["detail"])

    def test_corrupt_or_missing_linked_records_are_reported_without_substitutes(self):
        statement = self.id(STATEMENT, "0916a")
        linked = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=statement)
        link_file = self.root / "links" / f"{linked['capture_id']}.json"
        os.chmod(link_file, stat.S_IREAD | stat.S_IWRITE)
        link_file.write_bytes(link_file.read_bytes().replace(b'"headline_matches"', b'"headline_matched"'))
        page = self.overview("capture", linked["capture_id"])
        self.assertEqual((page["source"]["origin"]["state"], page["triage"]["state"]), ("unreadable", "origin_unreadable"))
        self.assertIn("left unchanged", page["source"]["origin"]["problem"])
        ghost = "20261009T150000000000Z-0123456789ab"  # A link naming a capture that does not exist.
        (self.root / "links" / f"{ghost}.json").write_text(json.dumps({"inbox": {"item_id": statement}}), encoding="utf-8")
        (self.root / "links" / "broken.json").write_text("{", encoding="utf-8")
        rows = {row["capture_id"]: row for row in self.overview("inbox", statement)["analysis"]["captures"]}
        self.assertIsNone(rows[ghost]["headline"])
        self.assertIn("cannot be read", rows[ghost]["problem"])
        self.assertEqual(self.overview("inbox", statement)["analysis"]["unreadable_links"], ["broken.json"])
        for kind, event_id in (("capture", ghost), ("inbox", "fed-monetary:0123456789abcdef0123"), ("other", "x")):
            self.overview(kind, event_id, status=404)


class TriageTests(Overview):
    def test_saved_triage_and_relations_belong_to_one_entry_version_and_are_suggestions(self):
        september, july, note = self.id(STATEMENT, "0916a"), self.id(STATEMENT, "0729a"), self.id(NOTE)
        self.process(september, note, provider=self.provider)
        page = self.overview("inbox", september)
        (mode,) = page["triage"]["modes"]
        self.assertEqual((mode["mode"], mode["status"], mode["result"]["category"]), ("simulated", "current",
                                                                                      "Policy decision"))
        self.assertIn("no model read the entry", mode["mode_note"])
        relation = next(item for item in page["triage"]["relations"] if item["relation"] == "possibly_same_event")
        self.assertEqual([other["item_id"] for other in relation["others"]], [note])
        self.assertTrue(relation["scope_checked"])
        self.assertEqual(self.overview("inbox", july)["triage"]["state"], "none")  # The same title, another event.
        self.no_calls_beyond(1)

    def no_calls_beyond(self, sent: int):
        self.assertEqual((len(self.feeds.requests), len(self.board.calls), len(self.provider.requests)), (0, 0, sent))


class RecheckOverviewTests(Recheck):
    def test_an_earlier_configuration_result_accepted_on_a_local_recheck_keeps_its_provenance(self):
        with TestClient(self.app(), base_url=BASE) as client:
            self.assertEqual(self.recheck(client).status_code, 201)
        app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                         self.root / "intake", self.root / "attempts", inbox=self.inbox, feeds=Network({}).fetcher(),
                         triage=self.triage, triage_senders=self.provider.senders(paid=True),
                         market=self.root / "market", context=self.root / "no-bundle", links=self.root / "links")
        calls = len(self.provider.requests)
        with patch.object(headline_triage, "PROMPT_VERSION", "triage-prompt-9"), \
                TestClient(app, base_url=BASE) as client:
            page = client.get(f"/api/events/inbox/{self.statement}").json()
        (mode,) = page["triage"]["modes"]
        provenance = mode["provenance"]
        self.assertEqual((mode["mode"], mode["status"], provenance["config"]["prompt_version"],
                          provenance["current_config"]), ("paid", "earlier_version", "triage-prompt-5", False))
        self.assertEqual((provenance["validation_policy"], provenance["revalidation"]["original_outcome"],
                          provenance["revalidation"]["original_validation_policy"]),
                         ("triage-validation-3", "not_accepted", "triage-validation-1"))
        self.assertEqual(len(self.provider.requests), calls)


class LocalReadTests(Overview):
    def test_overview_reads_and_reopening_fetch_write_and_approve_nothing(self):
        statement = self.id(STATEMENT, "0916a")
        linked = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=statement)
        self.mock(linked)
        board = FakeRelease(Clock(NOW))
        plan = market_retrieval.plan_view([f"capture-{linked['capture_id']}"], self.root / "market", None, self.inbox,
                                          self.root / "intake", None, self.clock)
        market_retrieval.dispatch(json.dumps({"plan_sha256": plan["plan_sha256"],
                                              "events": [f"capture-{linked['capture_id']}"], "attempt": 1}).encode(),
                                  self.root / "market", None, self.inbox, self.root / "intake", board.fetcher(), self.clock)
        before = fingerprint(self.root)
        for _ in range(2):
            for kind, event_id in (("inbox", statement), ("capture", linked["capture_id"])):
                page = self.overview(kind, event_id)
        self.assertEqual(page["market"]["state"], "complete")
        self.assertEqual(page["market"]["view"]["endpoints"]["base"], "2026-09-15")
        with TestClient(self.app(), base_url=BASE) as restarted:  # A server restart over the same folders.
            self.assertEqual(restarted.get(f"/api/events/capture/{linked['capture_id']}").json(), page)
        self.assertEqual(fingerprint(self.root), before)
        self.no_calls()
        self.assertEqual(len(board.calls), 1)  # Only the explicit dispatch above.

    def test_an_energy_or_trade_entry_gets_no_yields(self):
        answers = {**feeds(), **{url: queue for url, queue in QUIET.items()}}
        from test_event_inbox import EIA, eia_item, eia_rss
        answers[EIA] = [(200, eia_rss([eia_item(1, "Synthetic energy article")]))]
        self.refresh(answers, datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc))
        energy = self.id("Synthetic energy article")
        market = self.overview("inbox", energy)["market"]
        self.assertEqual((market["state"], market["view"]), ("unsupported", None))
        self.assertIn("outside this first slice", market["event"]["outside"])

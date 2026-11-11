"""The stories routes (user-api-0.5) and the News desk routes (admin-api-0.4) on the real application, with SYNTHETIC
accounts, terms, publishers and feeds (account_fakes, news_desk_fakes): reads that contact nothing and charge nothing,
Go deeper into the user's own analysis with every existing protection, the operator's explicit curation, and the paid
brief draft behind its cost decision. Nothing reaches a network."""
import json
import tempfile
import unittest
from pathlib import Path

from account_fakes import ADMIN_WRITE, USER_WRITE, World, every_file
from news_desk_fakes import (RESPONSE, RESPONSE_OWN, REVISION, START, TARIFF, BriefModel, Feeds, desk_in,
                             trade_feeds)
from second_order import (entitlements, news_feeds, news_registry, news_reports, news_stories, news_views,
                          story_briefs, usage)
from model_fixtures import FAKE_KEY

STORIES = "/api/user/news/stories"


class DeskWorld:
    """Accounts with synthetic terms and a desk whose SYNTHETIC feeds were refreshed, grouped and curated: a published
    brief on the tariff story and a topic of three developments."""

    def __init__(self, test: unittest.TestCase, terms: bool = True, drafting=None):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        if terms:
            self.world.standard_terms()
        self.network = Feeds(trade_feeds(START))
        self.desk = desk_in(self.world.root, network=self.network, drafting=drafting)
        synthetic = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, synthetic, lambda: START)
        self.keys = iter(f"desk-key-{number:06d}" for number in range(100_000))
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, next(self.keys))
        news_stories.merge(self.desk.newsroom, self.story(RESPONSE_OWN), {
            "into": self.story(RESPONSE), "reason": "same response", "idempotency_key": next(self.keys)},
            "setup", START)
        tariff = news_views.world(self.desk, START)["stories"][self.story(TARIFF)]
        content = {"headline": "Synthetic tariff on steel", "summary": "The Synthetic Republic said it would impose a "
                   "15% tariff on imported steel.", "facts": [{"text": "A 15% tariff was announced.", "reports": [
                       tariff["material"]["reports"][0]["entry_id"]]}],
                   "implications": [{"text": "Steel buyers could face higher costs if the tariff applies."}],
                   "themes": [], "uncertainties": ["How long it applies is not stated."], "missing": []}
        done, _ = story_briefs.add_version(self.desk.newsroom, tariff["story_id"], {
            "content": content, "method": "editorial", "based_on": None, "idempotency_key": next(self.keys)},
            tariff["material"], "setup", START)
        story_briefs.publish(self.desk.newsroom, tariff["story_id"], {"version": done["version"], "reason": "checked",
                                                                       "idempotency_key": next(self.keys)}, "setup",
                             START)

    def story(self, title: str) -> str:
        return next(story_id for story_id, story in news_views.world(self.desk, START)["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))

    def client(self, username: str):
        return self.world.client(username, desk=self.desk)

    def key(self) -> str:
        return next(self.keys)


class ReadsTest(unittest.TestCase):
    def test_reading_the_news_contacts_nothing_writes_nothing_and_charges_nothing(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        account = reader.get("/api/user/account").json()
        before, requests = every_file(world.world.root), len(world.network.requests)
        tariff = world.story(TARIFF)
        for path in (STORIES, f"{STORIES}?view=latest", f"{STORIES}?view=interests", f"{STORIES}/{tariff}",
                     f"{STORIES}/{tariff}/deeper", "/api/user/news/topics"):
            reply = reader.get(path)
            self.assertEqual(reply.status_code, 200, (path, reply.text))
            self.assertEqual(reply.json()["contract"], "user-api-0.5")
        self.assertEqual(every_file(world.world.root), before)  # No record, cache or store was written.
        self.assertEqual(len(world.network.requests), requests)
        self.assertEqual(world.world.provider.requests, [])
        self.assertEqual(reader.get("/api/user/account").json()["credits"], account["credits"])
        limits = reader.get("/api/user/limits").json()["limits"]
        self.assertEqual([row["used"] for row in limits["operations"]], [0, 0, 0, 0])

    def test_a_story_page_has_its_brief_its_sources_and_the_way_deeper(self):
        world = DeskWorld(self)
        story = world.client("reader-a").get(f"{STORIES}/{world.story(TARIFF)}").json()["story"]
        self.assertEqual(story["brief_state"], "published")
        self.assertEqual(story["brief"]["content"]["headline"], "Synthetic tariff on steel")
        self.assertEqual(story["brief"]["method_label"], story_briefs.METHOD_LABEL["editorial"])
        links = [row["link"] for row in story["sources"]]
        self.assertEqual(len(links), 2)
        self.assertTrue(all(link.startswith("https://") and "/news/" in link for link in links))
        self.assertEqual(story["coverage"]["reporting_origins"], 1)  # The wire copy repeats the first report.
        self.assertTrue(story["deeper"]["available"])
        for secret in ("setup", "desk-key-", "actor", "prepared_by", "history"):
            self.assertNotIn(secret, json.dumps(story))

    def test_a_merged_story_address_opens_the_story_it_joined(self):
        world = DeskWorld(self)
        merged = news_views.world(world.desk, START)["folded"]["merged_into"]
        old = next(iter(merged))
        story = world.client("reader-a").get(f"{STORIES}/{old}").json()["story"]
        self.assertEqual((story["merged"], story["story_id"]), (True, merged[old]["into_story_id"]))

    def test_the_news_needs_a_usage_policy_and_the_user_role(self):
        world = DeskWorld(self, terms=False)
        reader = world.client("reader-a")
        for path in (STORIES, f"{STORIES}/{world.story(TARIFF)}", "/api/user/news/topics"):
            self.assertEqual(reader.get(path).json()["code"], "no_usage_policy")
        self.assertEqual(world.client("admin").get(STORIES).status_code, 403)
        self.assertEqual(world.client("reader-a").get("/api/admin/news").status_code, 403)
        self.assertEqual(world.world.client(None, desk=world.desk).get(STORIES).status_code, 401)

    def test_unknown_stories_and_views_are_refused_in_the_contract_shape(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        self.assertEqual(reader.get(f"{STORIES}/story-0000000000000000").json()["code"], "not_found")
        self.assertEqual(reader.get(f"{STORIES}?view=popular").json()["code"], "invalid_request")
        self.assertEqual(reader.get("/api/user/news/topics/topic-x").json()["code"], "not_found")


class DeeperTest(unittest.TestCase):
    def deeper(self, client, story_id: str, effort: str = "low", material: str | None = None):
        preview = client.get(f"{STORIES}/{story_id}/deeper").json()["deeper"]
        return client.post(f"{STORIES}/{story_id}/deeper", headers=USER_WRITE,
                           json={"material_sha256": material or preview["material_sha256"], "effort": effort})

    def test_going_deeper_saves_the_users_own_source_and_prepares_without_running(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        tariff = world.story(TARIFF)
        preview = reader.get(f"{STORIES}/{tariff}/deeper").json()["deeper"]
        self.assertIn("not the publication", preview["source"]["text"])
        self.assertIn("(Reuters)", preview["source"]["text"])  # The feed's excerpt, as the feed gave it.
        first = self.deeper(reader, tariff)
        self.assertEqual(first.status_code, 201, first.text)
        done = first.json()["deeper"]
        self.assertEqual((done["created_source"], done["created_analysis"]), (True, True))
        self.assertEqual(done["analysis"]["state"], "prepared")
        again = self.deeper(reader, tariff)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["deeper"]["analysis"]["analysis_id"], done["analysis"]["analysis_id"])
        limits = {row["operation"]: row["used"] for row in reader.get("/api/user/limits").json()["limits"]["operations"]}
        self.assertEqual((limits["source"], limits["preparation"]), (1, 1))
        self.assertEqual(world.world.provider.requests, [])  # Nothing was quoted, sent or charged.
        self.assertIsNone(entitlements.attempt_record(world.world.accounts, request_id=done["analysis"]["analysis_id"]))
        page = reader.get(f"{STORIES}/{tariff}").json()["story"]
        self.assertEqual(page["brief"]["version"], 1)  # The shared brief is unchanged.

    def test_each_user_gets_their_own_analysis_and_never_sees_anothers(self):
        world = DeskWorld(self)
        tariff = world.story(TARIFF)
        mine = self.deeper(world.client("reader-a"), tariff).json()["deeper"]
        theirs = self.deeper(world.client("reader-b"), tariff).json()["deeper"]
        self.assertNotEqual(mine["source"]["source_id"], theirs["source"]["source_id"])
        other = world.client("reader-b")
        self.assertEqual(other.get(f"/api/user/analyses/{mine['analysis']['analysis_id']}").status_code, 404)
        self.assertEqual(other.get(f"/api/user/sources/{mine['source']['source_id']}").status_code, 404)
        existing = other.get(f"{STORIES}/{tariff}/deeper").json()["deeper"]["existing"]
        self.assertEqual(existing["source_id"], theirs["source"]["source_id"])

    def test_the_run_still_needs_its_quote_and_approval_and_runs_once(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        analysis = self.deeper(reader, world.story(TARIFF)).json()["deeper"]["analysis"]["analysis_id"]
        quote = reader.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        approval = {"quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                    "approve": True}
        run = reader.post(f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json=approval)
        self.assertEqual(run.status_code, 201, run.text)
        self.assertEqual(reader.post(f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE,
                                     json=approval).status_code, 200)
        self.assertEqual(len(world.world.provider.requests), 1)
        self.assertIn(b"Synthetic Republic announces 15% tariff", world.world.provider.requests[0])

    def test_changed_material_unknown_effort_and_unusable_material_are_refused(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        tariff = world.story(TARIFF)
        self.assertEqual(self.deeper(reader, tariff, material="0" * 64).json()["code"], "story_changed")
        self.assertEqual(self.deeper(reader, tariff, effort="max").json()["code"], "unsupported_effort")
        port = world.story("Synthetic port reports record container volumes")  # No stated time anywhere.
        self.assertEqual(self.deeper(reader, port).json()["code"], "deeper_unavailable")
        limits = reader.get("/api/user/limits").json()["limits"]["operations"]
        self.assertEqual([row["used"] for row in limits], [0, 0, 0, 0])
        bad = reader.post(f"{STORIES}/{tariff}/deeper", headers=USER_WRITE, json={"effort": "low"})
        self.assertEqual(bad.json()["code"], "invalid_request")


class DeskTest(unittest.TestCase):
    def test_the_desk_shows_the_registry_stories_and_their_records(self):
        world = DeskWorld(self)
        desk = world.client("admin").get("/api/admin/news").json()
        self.assertEqual(desk["contract"], "admin-api-0.4")
        publishers = {row["source"]: row for row in desk["desk"]["registry"]["publishers"]}
        self.assertEqual(publishers["reuters"]["status"], "needs_agreement")
        self.assertEqual(publishers["techcrunch"]["material"], "none")
        story = next(row for row in desk["desk"]["stories"] if row["story_id"] == world.story(TARIFF))
        self.assertEqual(story["history"][0]["basis"]["rule"], "story-match-0.1/new-report")
        self.assertEqual(story["published_version"], 1)
        self.assertFalse(desk["desk"]["drafting"]["enabled"])

    def test_the_operators_actions_are_explicit_and_idempotent(self):
        world = DeskWorld(self)
        admin = world.client("admin")
        topic = admin.post("/api/admin/news/topics", headers=ADMIN_WRITE, json={
            "title": "Synthetic steel dispute", "summary": "SYNTHETIC", "reason": "Ongoing", "idempotency_key": "t-key-0001"})
        self.assertEqual(topic.status_code, 201)
        self.assertEqual(admin.post("/api/admin/news/topics", headers=ADMIN_WRITE, json={
            "title": "Synthetic steel dispute", "summary": "SYNTHETIC", "reason": "Ongoing",
            "idempotency_key": "t-key-0001"}).status_code, 200)
        conflict = admin.post("/api/admin/news/topics", headers=ADMIN_WRITE, json={
            "title": "Other", "summary": "", "reason": "Ongoing", "idempotency_key": "t-key-0001"})
        self.assertEqual(conflict.json()["code"], "idempotency_conflict")
        topic_id = topic.json()["topic"]["topic_id"]
        for title in (TARIFF, RESPONSE, REVISION):
            reply = admin.post(f"/api/admin/news/topics/{topic_id}/links", headers=ADMIN_WRITE, json={
                "story_id": world.story(title), "action": "link", "label": "", "reason": "Part of it",
                "idempotency_key": world.key()})
            self.assertEqual(reply.status_code, 201, reply.text)
        timeline = world.client("reader-a").get(f"/api/user/news/topics/{topic_id}").json()["topic"]["timeline"]
        self.assertEqual([row["story_id"] for row in timeline],
                         [world.story(TARIFF), world.story(RESPONSE), world.story(REVISION)])  # As first reported.
        unbound = world.world.client("admin", bind=False, desk=world.desk).post(
            "/api/admin/news/topics", headers=ADMIN_WRITE, json={"title": "x", "summary": "", "reason": "x",
                                                                 "idempotency_key": "t-key-0002"})
        self.assertEqual(unbound.status_code, 428)

    def test_refreshing_publisher_feeds_uses_the_refresh_budget(self):
        world = DeskWorld(self)
        admin = world.client("admin")
        before = len(world.network.requests)
        reply = admin.post("/api/admin/news/feeds/refresh", headers=ADMIN_WRITE, json={})
        self.assertEqual(reply.status_code, 200, reply.text)
        expected = sorted(publisher.feed.feed_url for publisher in world.desk.publishers.values()
                          if (publisher.synthetic or publisher.status == "connected" and publisher.feed is not None)
                          and not publisher.feed.contact_required)  # SEC and ONS: only with the operator's contact.
        self.assertEqual(len(expected), len([row for row in news_registry.connected()
                                             if not row.feed.contact_required]) + 4)  # The registry's connected feeds
        # and four SYNTHETIC ones; the Event Inbox's official feeds are refreshed by the Inbox.
        self.assertEqual(sorted(world.network.requests[before:]), expected)  # Each registered feed once; no other.
        outcomes = {row["source"]: row["outcome"] for row in reply.json()["refresh"]["refreshed"]}
        self.assertEqual(outcomes["techcrunch"], "failed")  # The simulated network answers only SYNTHETIC feeds.
        self.assertEqual(usage.overview(world.world.accounts, world.world.root / "intake", world.world.clock())
                         ["server"]["refreshes"]["used"], 1)
        group = admin.post("/api/admin/news/group", headers=ADMIN_WRITE, json={"idempotency_key": "g-key-0001"}).json()
        self.assertEqual(group["grouping"]["grouped"], 0)  # The same reports: nothing new to group.

    def test_a_refresh_without_usage_limits_requests_nothing(self):
        world = DeskWorld(self, terms=False)
        before = len(world.network.requests)
        reply = world.client("admin").post("/api/admin/news/feeds/refresh", headers=ADMIN_WRITE, json={})
        self.assertEqual(reply.status_code, 409)
        self.assertEqual(len(world.network.requests), before)

    def test_briefs_are_saved_checked_and_published_by_explicit_actions(self):
        world = DeskWorld(self)
        admin = world.client("admin")
        revision = world.story(REVISION)
        draft = admin.get(f"/api/admin/news/stories/{revision}/draft").json()["draft"]
        self.assertFalse(draft["recorded"])
        saved = admin.post(f"/api/admin/news/stories/{revision}/briefs", headers=ADMIN_WRITE, json={
            "content": draft["content"], "method": "extract", "based_on": None, "idempotency_key": "b-key-0001"}).json()
        self.assertFalse(saved["brief"]["publishable"])
        refused = admin.post(f"/api/admin/news/stories/{revision}/publication", headers=ADMIN_WRITE, json={
            "version": 1, "reason": "try", "idempotency_key": "p-key-0001"}).json()
        self.assertEqual(refused["code"], "brief_not_publishable")
        self.assertTrue(refused["problems"])
        content = {**draft["content"], "implications": [{"text": "Mills could keep exempted grades if it lasts."}],
                   "uncertainties": ["Which grades is not stated."]}
        second = admin.post(f"/api/admin/news/stories/{revision}/briefs", headers=ADMIN_WRITE, json={
            "content": content, "method": "editorial", "based_on": 1, "idempotency_key": "b-key-0002"}).json()
        self.assertTrue(second["brief"]["publishable"])
        published = admin.post(f"/api/admin/news/stories/{revision}/publication", headers=ADMIN_WRITE, json={
            "version": 2, "reason": "checked", "idempotency_key": "p-key-0002"})
        self.assertEqual(published.status_code, 201)
        page = world.client("reader-a").get(f"{STORIES}/{revision}").json()["story"]
        self.assertEqual((page["brief_state"], page["brief"]["version"]), ("published", 2))


class DraftingTest(unittest.TestCase):
    def preview(self, world: DeskWorld, story: str):
        return world.client("admin").post(f"/api/admin/news/stories/{story}/drafting", headers=ADMIN_WRITE,
                                          json={}).json()["drafting"]

    def approve(self, world: DeskWorld, found: dict, **changes):
        return world.client("admin").post(f"/api/admin/news/drafting/{found['draft_id']}/approval",
                                          headers=ADMIN_WRITE, json={
            "request_sha256": found["request_sha256"], "approve_paid_request": True,
            "estimated_max_usd": found["estimate"]["estimated_real_run_if_output_reaches_max_usd"], **changes})

    def test_without_paid_drafting_the_cost_is_shown_and_nothing_is_sent(self):
        world = DeskWorld(self)
        found = self.preview(world, world.story(REVISION))
        self.assertGreater(found["estimate"]["estimated_real_run_if_output_reaches_max_usd"], 0)
        self.assertFalse(found["sending"]["enabled"])
        refused = self.approve(world, found)
        self.assertEqual(refused.json()["code"], "paid_drafting_disabled")
        folder = world.desk.newsroom.path.parent / "drafting" / found["draft_id"]
        self.assertFalse((folder / "attempt.json").exists())

    def test_an_approved_draft_is_sent_once_and_published_only_by_the_editors(self):
        model = BriefModel(FAKE_KEY)
        world = DeskWorld(self, drafting=model.sender())
        revision = world.story(REVISION)
        found = self.preview(world, revision)
        self.assertEqual(self.approve(world, found, estimated_max_usd=0.0001).json()["code"], "approval_mismatch")
        self.assertEqual(model.requests, [])
        sent = self.approve(world, found)
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(sent.json()["drafting"]["attempt"]["state"], "validated")  # Stage 1: no version yet.
        self.assertEqual(self.approve(world, found).json()["sent"], False)
        self.assertEqual(len(model.requests), 1)
        second = self.preview(world, revision)
        self.assertEqual((second["stage"], second["state"]), (2, "awaiting_stage_2"))
        sent = self.approve(world, second)
        self.assertEqual(sent.json()["drafting"]["attempt"]["state"], "recorded")
        self.assertEqual(self.approve(world, second).json()["sent"], False)
        self.assertEqual(model.stages(), [1, 2])
        page = world.client("reader-a").get(f"{STORIES}/{revision}").json()["story"]
        self.assertEqual(page["brief_state"], "none")  # Saved as a version; not published.
        admin = world.client("admin")
        admin.post(f"/api/admin/news/stories/{revision}/publication", headers=ADMIN_WRITE, json={
            "version": 1, "reason": "checked", "idempotency_key": "p-key-0003"})
        page = world.client("reader-a").get(f"{STORIES}/{revision}").json()["story"]
        self.assertEqual(page["brief"]["method"], "model")
        self.assertNotIn("claude", json.dumps(page).lower())  # No model or provider name reaches a user.
        self.assertNotIn("usd", json.dumps(page).lower())

    def test_a_reply_carrying_the_key_is_not_kept(self):
        model = BriefModel(FAKE_KEY)
        model.echo = True
        world = DeskWorld(self, drafting=model.sender())
        found = self.preview(world, world.story(REVISION))
        done = self.approve(world, found).json()["drafting"]
        self.assertEqual(done["attempt"]["state"], "invalid")
        folder = world.desk.newsroom.path.parent / "drafting" / found["draft_id"]
        self.assertFalse((folder / "response.json").exists())


if __name__ == "__main__":
    unittest.main()

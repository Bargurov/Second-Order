"""Context for economic explanations (econ-context-0.2, econ-explanation-0.3) and coverage baselines
(news-baseline-0.1), over SYNTHETIC feeds (news_desk_fakes): every context item says its role, why it is relevant and
when it was published against the story's first report; later context is labelled and never the basis of what
happened; methodology and earlier releases are matched by structure, not words; newer context makes an explanation
outdated until it is prepared with it; a page says precisely what was read; and a baseline keeps the stories selected
at a cutoff apart from those listed later. Nothing reaches a network."""
import copy
from datetime import timedelta
import json
import unittest
from unittest import mock

from account_fakes import every_file
from news_desk_fakes import (COURIER, MOBILE, RESPONSE, SALES, START, TARIFF, UNRELATED, assess, economics_items,
                             item, tariff_economics, trade_feeds)
from second_order import (econ_context, news_baseline, news_batches, news_reports, news_stories, news_views,
                          story_economics)
from second_order.accounts import AccountsRefused
from test_news_economics import World, figure, sales


def observation(published: str, **changes) -> dict:
    row = {"kind": "observation", "role": "event_evidence", "source": "SYNTHETIC statistics office release",
           "url": "https://example.org/synthetic-release", "published": published, "as_of": published,
           "retrieved": "2026-10-26", "terms": "SYNTHETIC test item",
           "relevance": "SYNTHETIC: the release's own statement of the September figure.",
           "text": "SYNTHETIC: retail sales were revised to $746.2 billion in September."}
    row.update(changes)
    return row


def library(source: str = "synthetic-courier", title: str = SALES) -> dict:
    return {"methodology_version": econ_context.METHODOLOGY_VERSION, "statement": "SYNTHETIC library",
            "series": [{"series_id": "synthetic-sales", "source": source, "titles": [title],
                        "publisher": "Synthetic Courier", "document": "SYNTHETIC release notes",
                        "url": "https://courier.example.org/notes", "published": "2026-10-01",
                        "retrieved": "2026-10-26", "terms": "SYNTHETIC test item",
                        "checked_against": {"text_sha256": "0" * 64, "statement": "SYNTHETIC"},
                        "passages": [{"text": "SYNTHETIC: ranges are 90 percent confidence intervals.",
                                      "defines": ["confidence interval"],
                                      "relevance": "SYNTHETIC: how to read the range beside a change."}]}]}


class ContextItemTest(unittest.TestCase):
    def build(self, world: World, title: str, **options):
        return econ_context.build(world.desk, news_views.world(world.desk, START), world.story_id(title), START,
                                  "editor-1", **options)

    def test_every_supplied_item_says_its_role_why_it_is_relevant_and_when_it_was_retrieved(self):
        world = World(self)
        legacy = {key: value for key, value in observation("2026-10-14").items()
                  if key not in ("role", "retrieved", "relevance")}
        for row, why in ((legacy, "exactly"), (observation("2026-10-14", role="benchmark"), "role"),
                         (observation("2026-10-14", relevance=" "), "relevance")):
            with self.subTest(why=why), self.assertRaises(AccountsRefused) as refused:
                self.build(world, SALES, supplied={"items": [row]})
            self.assertIn(why, str(refused.exception))
        bundle, _ = self.build(world, SALES, supplied={"items": [observation("2026-10-14")]})
        kept = bundle["items"][0]
        self.assertEqual((kept["role"], kept["retrieved"], kept["timing"], bundle["context_version"]),
                         ("event_evidence", "2026-10-26", "same_day", econ_context.CONTEXT_VERSION))
        self.assertEqual(bundle["story_first_reported"][:10], "2026-10-14")
        self.assertIn("release's own statement", kept["relevance"])

    def test_later_context_is_labelled_and_never_the_basis_of_what_happened(self):
        world = World(self)
        bundle, _ = self.build(world, SALES, supplied={"items": [observation("2026-10-20")]})
        self.assertEqual(bundle["items"][0]["timing"], "after")
        revised = figure("f9", 746.2, "retail sales were revised to $746.2 billion", source="context:o1",
                         unit="billion dollars", measure="level", period="September", label="Revised sales")
        planted = sales("SYNTHETIC: it may matter for retailers.")  # Planted: later context as what happened.
        planted["figures"].append(revised)
        planted["change"]["basis"].append("context:o1")
        self.assertIn("retrospective_as_event", world.rules(SALES, planted, bundle))
        planted = sales("SYNTHETIC: it may matter for retailers.",
                        change="SYNTHETIC: sales were {f9} in September, the release says.")
        planted["figures"].append(revised)
        self.assertIn("retrospective_as_event", world.rules(SALES, planted, bundle))  # Through its figure.
        fair = sales("SYNTHETIC: it may matter for retailers.")
        fair["figures"].append(revised)
        fair["alternatives"].append({"kind": "competing_explanation", "support": "event_evidence",
                                     "basis": ["context:o1"], "assumptions": [],
                                     "text": "SYNTHETIC: a later revision put sales at {f9}, so the first estimate "
                                             "may have been low."})
        row = world.save(SALES, fair, bundle)
        self.assertNotIn("retrospective_as_event", {finding["rule"] for finding in row["guard"]["findings"]})
        view = story_economics.reader_view(row["content"]["economics"], row["content"]["facts"],
                                           row["preparation"]["analysis"])
        shown = view["context"][0]
        self.assertEqual((shown["retrospective"], shown["role"], shown["timing"]), (True, "event_evidence", "after"))
        self.assertIn("not what was known", shown["timing_label"])
        alternative = view["alternatives"][-1]["basis"]
        self.assertIn("published after this story was first reported", alternative[0]["label"])
        statement = story_economics.context_statement(row["content"]["economics"])
        self.assertIn("One of these items was published after this story was first reported", statement)

    def test_the_page_says_what_was_read_beyond_the_material_and_that_passages_are_not_the_publication(self):
        world = World(self)
        bundle, _ = self.build(world, SALES, supplied={"items": [observation("2026-10-14")]})
        cited = sales("SYNTHETIC: it may matter for retailers.")
        cited["significance"]["basis"].append("context:o1")
        row = world.save(SALES, cited, bundle)
        world.publish(world.story_id(SALES), row["version"])
        page = news_views.story_view(world.desk, world.story_id(SALES), START)
        statement = page["brief"]["context_statement"]
        self.assertIn("1 quoted passage of SYNTHETIC statistics office release (on this development)", statement)
        self.assertIn("the documents were not otherwise used", statement)
        self.assertNotIn("full text", statement)
        self.assertIn("feed excerpts", page["brief"]["material"]["statement"])  # The material itself is unchanged.
        bare = world.save(SALES, sales("SYNTHETIC: it may matter for retailers."))
        self.assertIsNone(story_economics.context_statement(bare["content"]["economics"]))


class StructureTest(unittest.TestCase):
    """Methodology and earlier releases are matched by feed and release title, never by shared words."""

    def test_methodology_is_matched_by_feed_and_release_title(self):
        world = World(self)
        found = news_views.world(world.desk, START)
        sales_story, mobile_story = found["stories"][world.story_id(SALES)], found["stories"][world.story_id(MOBILE)]
        with mock.patch.object(econ_context, "methodology", return_value=library()):
            self.assertEqual([row["series_id"] for row in econ_context.methodology_for(sales_story)],
                             ["synthetic-sales"])
            self.assertEqual(econ_context.methodology_for(mobile_story), [])  # Same feed, another series.
            bundle, _ = econ_context.build(world.desk, found, sales_story["story_id"], START, "editor-1",
                                           use_methodology=True)
            self.assertEqual([(row["item_id"], row["kind"], row["role"]) for row in bundle["items"]],
                             [("m1", "methodology", "methodology")])
            self.assertIn("how to read the range", bundle["items"][0]["relevance"])
            self.assertEqual(bundle["items"][0]["timing"], "before")
            with self.assertRaises(AccountsRefused) as refused:
                econ_context.build(world.desk, found, mobile_story["story_id"], START, "editor-1",
                                   use_methodology=True)
            self.assertEqual(refused.exception.code, "no_methodology")
        with mock.patch.object(econ_context, "methodology", return_value=library(source="synthetic-ledger")):
            self.assertEqual(econ_context.methodology_for(sales_story), [])  # Same title, another feed.

    def test_the_library_is_checked_and_each_passage_says_what_it_defines_and_why(self):
        econ_context.methodology.cache_clear()
        found = econ_context.methodology()
        self.assertTrue(found["series"])
        for series in found["series"]:
            self.assertTrue(series["url"].startswith("https://"))
            self.assertEqual(len(series["checked_against"]["text_sha256"]), 64)
            for passage in series["passages"]:
                self.assertTrue(passage["defines"] and passage["relevance"])
        broken = copy.deepcopy(library())
        broken["series"][0]["passages"][0].pop("relevance")
        with mock.patch.object(econ_context.METHODOLOGY.__class__, "read_text", return_value=json.dumps(broken)):
            econ_context.methodology.cache_clear()
            with self.assertRaises(ValueError):
                econ_context.methodology()
        econ_context.methodology.cache_clear()

    def test_the_previous_release_of_the_same_series_is_found_and_a_later_one_never_is(self):
        earlier = item(COURIER.link_host, "sales-august", SALES, START - timedelta(days=30),
                       "SYNTHETIC: Retail sales were $739.1 billion in August.")
        similar = item(COURIER.link_host, "sales-other", "Synthetic retail sales reach a record", START -
                       timedelta(days=20), "SYNTHETIC: a different series.")
        world = World(self, extra=[earlier, similar])
        found = news_views.world(world.desk, START)
        current = max((story for story in found["stories"].values() if story["title"] == SALES),
                      key=lambda story: story["first_at"])
        previous = econ_context.earlier_release(found, current)
        self.assertIsNotNone(previous)
        self.assertEqual((previous["title"], previous["first_at"][:10]), (SALES, "2026-09-14"))
        self.assertIsNone(econ_context.earlier_release(found, previous))  # Nothing before the first one.
        suggested = econ_context.candidates(world.desk, found, current["story_id"])["candidates"]
        self.assertEqual([(row["option"], row["story_id"]) for row in suggested],
                         [("--earlier-release", previous["story_id"])])
        bundle, _ = econ_context.build(world.desk, found, current["story_id"], START, "editor-1",
                                       use_earlier_release=True)
        self.assertEqual({(row["role"], row["timing"]) for row in bundle["items"]}, {("comparison", "before")})
        self.assertIn("previous release of the same series", bundle["items"][0]["relevance"])


class NewerContextTest(unittest.TestCase):
    def test_newer_context_makes_an_explanation_outdated_until_it_is_prepared_with_it(self):
        world = World(self)
        story_id = world.story_id(TARIFF)
        row = world.save(TARIFF, tariff_economics())
        world.publish(story_id, row["version"])
        state = lambda: news_views.story_view(world.desk, story_id, START)["explanation"]  # noqa: E731
        self.assertEqual(state()["state"], "ready")
        found = news_views.world(world.desk, START)
        bundle, _ = econ_context.build(world.desk, found, story_id, START + timedelta(hours=1), "editor-1",
                                       with_stories=[(world.story_id(RESPONSE), "SYNTHETIC: the response.")])
        self.assertEqual(state()["state"], "outdated")
        self.assertIn("newer context was gathered", state()["reason"])
        batch, _ = news_batches.preview(world.desk, START, "assisted", 1, story_ids=[story_id])
        self.assertEqual(batch["items"][0]["context"]["bundle_id"], bundle["bundle_id"])
        again = world.save(TARIFF, tariff_economics(), bundle)
        world.publish(story_id, again["version"])
        self.assertEqual(state()["state"], "ready")

    def test_context_built_before_an_explanation_was_prepared_does_not_outdate_it(self):
        world = World(self)
        story_id = world.story_id(TARIFF)
        econ_context.build(world.desk, news_views.world(world.desk, START), story_id, START - timedelta(hours=1),
                           "editor-1", with_stories=[(world.story_id(RESPONSE), "SYNTHETIC: the response.")])
        row = world.save(TARIFF, tariff_economics())  # Prepared after it, without it: the preparer's choice.
        world.publish(story_id, row["version"])
        self.assertEqual(news_views.story_view(world.desk, story_id, START)["explanation"]["state"], "ready")


class BaselineTest(unittest.TestCase):
    def test_a_baseline_is_recorded_once_and_progress_keeps_later_stories_apart(self):
        world = World(self)
        baseline, created = news_baseline.record(world.desk, START, "editor-1", "SYNTHETIC: the pending work")
        again, created_again = news_baseline.record(world.desk, START, "editor-1", "SYNTHETIC: the pending work")
        self.assertEqual((created, created_again, again["baseline_id"]), (True, False, baseline["baseline_id"]))
        listed = {row["story_id"]: row for row in baseline["stories"]}
        self.assertEqual(listed[world.story_id(TARIFF)]["explanation_state"], "pending")
        row = world.save(TARIFF, tariff_economics())
        world.publish(world.story_id(TARIFF), row["version"])
        later = START + timedelta(hours=2)
        fresh = item(COURIER.link_host, "fresh", "Synthetic exporters report record orders",
                     later - timedelta(minutes=30), "SYNTHETIC: exporters reported record orders.")
        world.network.answers.update(trade_feeds(START, economics_items(START) + [fresh]))
        world.refresh(later)
        reports = news_reports.pool(world.desk.inbox, world.desk.feeds, world.desk.publishers)["reports"]
        news_stories.group(world.desk.newsroom, reports, set(), "setup", later, "group-key-0002")
        assess(world.desk, START, {UNRELATED: "outside_scope"})  # As before, and the new story's.
        before = every_file(world.root)
        progress = news_baseline.progress(world.desk, baseline["baseline_id"], later)
        self.assertEqual(every_file(world.root), before)  # Reading progress writes nothing.
        rows = {row["story_id"]: row for row in progress["stories"]}
        tariff = rows[world.story_id(TARIFF)]
        self.assertEqual((tariff["then"]["explanation_state"], tariff["now"]["explanation_state"],
                          tariff["new_version"]), ("pending", "ready", True))
        self.assertEqual(progress["counts_now"]["ready"], progress["counts_then"]["ready"] + 1)
        fresh = [row for row in progress["outside_baseline"]["rows"]
                 if row["title"] == "Synthetic exporters report record orders"]
        self.assertEqual(len(fresh), 1)
        self.assertTrue(fresh[0]["first_reported_after_cutoff"])
        self.assertNotIn(fresh[0]["story_id"], rows)
        self.assertEqual(sum(progress["counts_now"].values()), len(baseline["stories"]))
        with self.assertRaises(AccountsRefused):
            news_baseline.load(world.desk, "baseline-0000000000000000")
        self.assertEqual(news_baseline.listing(world.desk)[0]["baseline_id"], baseline["baseline_id"])


if __name__ == "__main__":
    unittest.main()

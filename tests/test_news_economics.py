"""Shared economic explanations of news stories (econ-explanation-0.1, story-brief-0.3, news-batch-0.2), over SYNTHETIC
feeds (news_desk_fakes): contrasting cases and planted mistakes against the evidence boundary, and the reusable
workflow that prepares, records, publishes and shows an explanation for any eligible story.

The planted mistakes are the ones an explanation must not make: a domestic service's price read through an import
tariff's mechanism, a nominal figure called real, a level presented as a change, a percent change of growth rates, a
surprise without an expectations benchmark, a second-order effect without a channel or a condition, a number or a
company the evidence does not hold, a comparison with the past without evidence, a security price forecast. These
checks are of shape, evidence and words: passing them is not evidence that an explanation is economically right
(docs/economic-review-rubric.md). Nothing reaches a network."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from account_fakes import every_file
from news_desk_fakes import (COURIER, GROWTH, MOBILE, RESPONSE, RESPONSE_OWN, SALES, START, TARIFF, UNRELATED,
                             BriefModel, Feeds, assess, both_stages, desk_in, economics_items, item, tariff_economics,
                             trade_feeds, with_report)
from second_order import (brief_drafting, brief_stages, econ_context, econ_framework, news_batches, news_explanations,
                          news_feeds, news_reports, news_stories, news_views, story_briefs, story_economics)
from second_order import newsroom_store as ns
from second_order.accounts import AccountsRefused

KEY = "sk-ant-dummy-simulated-economics-key-001"


class World:
    """The SYNTHETIC trade dispute and three economic reports, grouped, the response merged, every story assessed as
    relevant except the museum (outside the scope)."""

    def __init__(self, test: unittest.TestCase, model: bool = False, extra: list[str] | None = None):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.network = Feeds(trade_feeds(START, economics_items(START) + (extra or [])))
        self.model = BriefModel(KEY) if model else None
        self.desk = desk_in(self.root, network=self.network, drafting=self.model.sender() if model else None)
        self.refresh(START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        news_stories.merge(self.desk.newsroom, self.story_id(RESPONSE_OWN), {
            "into": self.story_id(RESPONSE), "reason": "one response", "idempotency_key": "merge-key-0001"}, "setup",
            START)
        assess(self.desk, START, {UNRELATED: "outside_scope"})
        self.ticks = iter(START + timedelta(seconds=n) for n in range(100_000))
        self.keys = iter(f"econ-key-{n:05d}" for n in range(100_000))

    def refresh(self, moment) -> None:
        synthetic = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, synthetic, lambda: moment)

    def clock(self):
        return next(self.ticks)

    def story_id(self, title: str) -> str:
        return next(story_id for story_id, story in news_views.world(self.desk, START)["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))

    def story(self, title: str) -> dict:
        return news_views.world(self.desk, START)["stories"][self.story_id(title)]

    def first(self, title: str) -> str:
        return self.story(title)["material"]["reports"][0]["entry_id"]

    def brief(self, title: str, economics: dict | None = None) -> dict:
        story = self.story(title)
        content = {"headline": f"SYNTHETIC: {title}"[:160], "summary": "SYNTHETIC: the report states a development.",
                   "facts": [{"text": f"SYNTHETIC: {title}.", "reports": [self.first(title)]}],
                   "implications": [{"text": "SYNTHETIC: it could matter if it lasts."}], "themes": [],
                   "uncertainties": ["SYNTHETIC: how long it lasts is not stated."], "missing": []}
        if economics is not None:
            content["economics"] = with_report(economics, self.first(title))
        return content

    def save(self, title: str, economics: dict | None, bundle: dict | None = None) -> dict:
        """Save an editor's version with this explanation; returns the saved row (or raises AccountsRefused)."""
        story = self.story(title)
        basis = story_economics.evidence(story["material"], None, bundle, story["first_at"])
        done, _ = story_briefs.add_version(self.desk.newsroom, story["story_id"], {
            "content": self.brief(title, economics), "method": "editorial", "based_on": None,
            "idempotency_key": next(self.keys)}, story["material"], "editor-1", START, basis=basis)
        return next(row for row in ns.state(self.desk.newsroom)["briefs"][story["story_id"]]
                    if row["version"] == done["version"])

    def rules(self, title: str, economics: dict, bundle: dict | None = None) -> set[str]:
        """The guard rules that stop this explanation's publication."""
        return {row["rule"] for row in self.save(title, economics, bundle)["guard"]["findings"]}

    def publish(self, story_id: str, version: int) -> None:
        story_briefs.publish(self.desk.newsroom, story_id, {"version": version, "reason": "SYNTHETIC",
                                                            "idempotency_key": next(self.keys)}, "editor-1", START)


def explanation(**parts) -> dict:
    """A minimal SYNTHETIC explanation citing the story's first fact, with ``parts`` replaced."""
    base = {"status": "explained", "insufficient_reason": None,
            "change": {"stage": "implementation", "instrument": "other", "form": "reported_observation",
                       "respondents": None, "basis": ["fact:1"], "text": "SYNTHETIC: the report states a change."},
            "significance": {"basis": ["fact:1"], "text": "SYNTHETIC: it may matter for those it concerns."},
            "main_uncertainty": "SYNTHETIC: how long it lasts.", "figures": [], "calculations": [],
            "assumptions": [],
            "channels": [{"id": "m1", "scope": "micro", "support": "event_evidence", "note": None,
                          "steps": ["SYNTHETIC step"],
                          "text": "SYNTHETIC: those concerned could adjust their spending.",
                          "affected": [{"kind": "households", "name": "SYNTHETIC users", "how": "could pay more"}],
                          "conditions": None, "horizon": "months", "basis": ["fact:1"], "assumptions": []}],
            "second_order": [], "alternatives": [{"kind": "offsetting_force", "support": "event_evidence",
                                                  "basis": ["fact:1"], "assumptions": [],
                                                  "text": "SYNTHETIC: other prices might fall."}],
            "watch": [{"observable": "SYNTHETIC: the next report", "would": "support",
                       "text": "A further rise would support the reading."}]}
    base.update(parts)
    return base


def figure(fid: str, value, quote: str, **extra) -> dict:
    row = {"id": fid, "label": "SYNTHETIC figure", "value": value, "unit": "percent", "measure": "growth_rate",
           "period": "this month", "basis": "nominal", "seasonal": "not_stated", "price": False,
           "source": "report:{report}", "quote": quote, "vintage_label": None, "sign": "as_quoted",
           "sign_words": None, "bound": "exact", "statistic": "observed", "stock_flow": "not_applicable"}
    row.update(extra)
    return row


def mobile(note: str | None = "consumer-price-weights", instrument: str = "domestic_price") -> dict:
    """The domestic service's price: a 40% rise in mobile internet charges, explained through consumer prices."""
    return explanation(
        change={"stage": "implementation", "instrument": instrument, "form": "reported_observation",
                "respondents": None, "basis": ["fact:1", "figure:f1"],
                "text": "SYNTHETIC: operators raised mobile internet charges by {f1}, the regulator said."},
        figures=[figure("f1", 40, "rose 40% this month", price=True)],
        channels=[{"id": "m1", "scope": "micro", "support": "framework" if note else "event_evidence", "note": note,
                   "horizon": "immediate", "basis": ["fact:1", "figure:f1"],
                   "assumptions": [], "conditions": None, "steps": ["Charges for mobile internet rise by {f1}",
                                                                    "Users' spending on the service could rise"],
                   "text": "SYNTHETIC: households that use mobile internet could pay more for it; the overall "
                           "price level would move only by the service's weight.",
                   "affected": [{"kind": "households", "name": "mobile internet users", "how": "could pay more"}]}])


SALES_FIGURES = [
    {**figure("f1", 745.0, "Retail sales were $745.0 billion in September", unit="billion dollars", measure="level",
              period="September 2026", stock_flow="flow_per_month")},
    {**figure("f2", 739.1, "August's $739.1 billion", unit="billion dollars", measure="level", period="August 2026",
              stock_flow="flow_per_month")},
    {**figure("f3", 3.1, "Consumer prices were 3.1% higher than a year earlier", period="the year to September 2026",
              basis="not_applicable", price=True)}]


def sales(significance: str, change: str = "SYNTHETIC: retail sales were {f1} in September.", **parts) -> dict:
    return explanation(
        change={"stage": "observation", "instrument": "economic_activity", "form": "reported_observation",
                "respondents": None, "basis": ["fact:1", "figure:f1"], "text": change},
        significance={"basis": ["fact:1", "calc:c1", "figure:f3"], "text": significance},
        figures=copy.deepcopy(SALES_FIGURES),
        calculations=[{"id": "c1", "op": "percent_change", "inputs": ["f1", "f2"], "label": "Change on August"}],
        **parts)


def growth(op: str) -> dict:
    return explanation(
        change={"stage": "observation", "instrument": "economic_activity", "form": "reported_observation",
                "respondents": None, "basis": ["fact:1"],
                "text": "SYNTHETIC: growth was {f1} in the third quarter, after {f2}."},
        significance={"basis": ["calc:c1"], "text": "SYNTHETIC: growth changed by {c1} between the quarters."},
        figures=[figure("f1", 2.5, "annual rate of 2.5% in the third quarter", period="2026 Q3", basis="real",
                        seasonal="seasonally_adjusted"),
                 figure("f2", 2.0, "after 2.0% in the second quarter", period="2026 Q2", basis="real",
                        seasonal="seasonally_adjusted")],
        calculations=[{"id": "c1", "op": op, "inputs": ["f1", "f2"], "label": "Change in growth"}])


class ContrastTest(unittest.TestCase):
    """The same word, different economics: an import tariff against a domestic service's "tariff"."""

    def test_an_import_tariff_is_explained_through_the_tariff_mechanism(self):
        world = World(self)
        row = world.save(TARIFF, tariff_economics())
        self.assertEqual(row["guard"]["findings"], [])
        economics = row["content"]["economics"]
        self.assertEqual((economics["change"]["instrument"], economics["channels"][0]["note"]),
                         ("import_tariff", "tariff-pass-through"))
        self.assertEqual(row["preparation"]["analysis"]["analysis_version"], story_economics.ANALYSIS_VERSION)

    def test_a_domestic_service_charge_is_not_read_through_the_import_tariff_mechanism(self):
        world = World(self)
        self.assertEqual(world.rules(MOBILE, mobile()), set())  # Its own mechanism: one price in the price level.
        with self.assertRaises(AccountsRefused) as refused:  # Planted: the tariff mechanism for a domestic price.
            world.save(MOBILE, mobile(note="tariff-pass-through"))
        self.assertIn("applies to", str(refused.exception))
        # Planted: classified as an import tariff although its evidence never speaks of imports or duties.
        self.assertIn("instrument_unsupported", world.rules(MOBILE, mobile(note=None, instrument="import_tariff")))


class EvidenceBoundaryTest(unittest.TestCase):
    def test_nominal_and_real_levels_and_growth_are_kept_apart(self):
        world = World(self)
        good = sales("SYNTHETIC: nominal sales were {c1} higher than in August; with consumer prices {f3} higher "
                     "over the year, part of the rise may reflect prices rather than volumes.")
        self.assertEqual(world.rules(SALES, good), set())
        self.assertIn("real_nominal", world.rules(SALES, sales(  # Planted: a nominal change called real.
            "SYNTHETIC: real retail sales rose {c1} on the month.")))
        self.assertIn("level_as_change", world.rules(SALES, sales(  # Planted: a level presented as a change.
            "SYNTHETIC: it may matter for retailers.", change="SYNTHETIC: retail sales rose by {f1} in September.")))
        self.assertEqual(world.rules(GROWTH, growth("difference")), set())  # Growth rates differ in points.
        with self.assertRaises(AccountsRefused) as refused:  # Planted: "growth rose 25%" from 2.0% to 2.5%.
            world.save(GROWTH, growth("percent_change"))
        self.assertIn("levels", str(refused.exception))

    def test_a_surprise_needs_a_contemporaneous_expectations_benchmark(self):
        world = World(self)
        claim = "SYNTHETIC: sales rose {c1}, more than expected by forecasters."
        self.assertIn("unsupported_expectation", world.rules(SALES, sales(claim)))  # Planted: no benchmark.
        for as_of, finds in (("2026-10-10", False), ("2026-10-20", True)):  # Before the release, or after it.
            with self.subTest(as_of=as_of):
                found = news_views.world(world.desk, START)
                benchmark = {"kind": "expectation", "role": "benchmark", "source": "SYNTHETIC survey of forecasters",
                             "url": "https://example.org/synthetic-survey", "published": as_of, "as_of": as_of,
                             "retrieved": as_of, "terms": "SYNTHETIC test item",
                             "relevance": "SYNTHETIC: the forecasters' expectation for the release.",
                             "text": "SYNTHETIC: forecasters expected sales of $742.0 billion."}
                bundle, _ = econ_context.build(world.desk, found, world.story_id(SALES), START, "editor-1",
                                               supplied={"items": [benchmark]})
                cited = sales(claim)
                cited["significance"]["basis"].append("context:e1")
                self.assertEqual("unsupported_expectation" in world.rules(SALES, cited, bundle), finds)

    def test_second_order_effects_need_a_channel_a_condition_and_a_hedge(self):
        world = World(self)
        good = tariff_economics()
        for change, why in ((lambda e: e["second_order"][0].update({"from": "m9"}), "channels"),
                            (lambda e: e["second_order"][0].update({"conditions": ""}), "conditions"),
                            (lambda e: e["channels"][0].update({"basis": []}), "basis"),
                            (lambda e: (e["change"].update({"stage": "proposal"}),
                                        e["channels"][0].update({"conditions": None})), "condition")):
            planted = copy.deepcopy(good)
            change(planted)
            with self.subTest(why=why), self.assertRaises(AccountsRefused) as refused:
                world.save(TARIFF, planted)
            self.assertIn(why, str(refused.exception))
        unhedged = copy.deepcopy(good)
        unhedged["second_order"][0]["text"] = "SYNTHETIC: domestic steelmakers gain sales."
        self.assertIn("unhedged", world.rules(TARIFF, unhedged))
        none = copy.deepcopy(good)
        none["second_order"] = []
        self.assertEqual(world.rules(TARIFF, none), set())  # None is better than an invented one.

    def test_numbers_companies_comparisons_and_prices_come_only_from_the_evidence(self):
        world = World(self)
        cases = {
            "unsourced_number": lambda e: e["channels"][0].update(
                text="SYNTHETIC: steel imports could fall by 20% if buyers switch."),
            "company_not_in_evidence": lambda e: e["channels"][0]["affected"].append(
                {"kind": "firms", "name": "Synthetic Steelworks Ltd", "how": "could pay more"}),
            "historical_comparison": lambda e: e["watch"].append(
                {"observable": "SYNTHETIC: steel prices", "would": "support",
                 "text": "Prices higher than a year earlier would support it."}),
            "price_forecast": lambda e: e["alternatives"].append(
                {"kind": "competing_explanation", "support": "bounded_inference", "basis": [], "assumptions": ["a1"],
                 "text": "SYNTHETIC: steel shares could fall if demand weakens."}),
            "advice": lambda e: e["watch"].append(
                {"observable": "SYNTHETIC: the decree", "would": "support", "text": "Investors should watch it."}),
            "causal_claim": lambda e: e["significance"].update(
                text="SYNTHETIC: the duty of {f1} caused higher steel costs."),
            "certainty": lambda e: e["channels"][0].update(
                text="SYNTHETIC: the duty is guaranteed to raise what steel buyers pay, if applied."),
        }
        for rule, plant in cases.items():
            planted = copy.deepcopy(tariff_economics())
            plant(planted)
            with self.subTest(rule=rule):
                self.assertIn(rule, world.rules(TARIFF, planted))
        named = copy.deepcopy(tariff_economics())  # A company the evidence names is fine, and so is a market share.
        named["channels"][0]["affected"].append({"kind": "firms", "name": "Synthetic Republic importers",
                                                 "how": "could pay the duty"})
        named["second_order"][0]["text"] = "SYNTHETIC: domestic steelmakers could gain market share."
        named["alternatives"][0]["text"] = "SYNTHETIC: guaranteed loans to steel buyers might soften the cost."
        named["watch"][0]["text"] = "A rise in the import share would weaken the reading; a decline would support it."
        self.assertEqual(world.rules(TARIFF, named), set())

    def test_figures_quote_their_evidence_and_derived_figures_are_never_written_by_hand(self):
        world = World(self)
        invented = sales("SYNTHETIC: it may matter.")
        invented["figures"][0]["quote"] = "Retail sales were $760.0 billion"
        with self.assertRaises(AccountsRefused):
            world.save(SALES, invented)
        handmade = sales("SYNTHETIC: it may matter.")
        handmade["calculations"][0]["value"] = 0.8  # A drafter's own result is refused: the code computes it.
        with self.assertRaises(AccountsRefused):
            world.save(SALES, handmade)
        row = world.save(SALES, sales("SYNTHETIC: nominal sales were {c1} higher than in August."))
        computed = row["content"]["economics"]["calculations"][0]
        self.assertEqual((computed["display"], computed["formula"]), ("+0.8%", "(f1 ÷ f2 − 1) × 100"))

    def test_insufficient_evidence_is_a_valid_explanation_and_holds_nothing_else(self):
        world = World(self)
        row = world.save(MOBILE, {**{key: [] for key in story_economics.FIELDS[5:]}, "status": "insufficient_evidence",
                                  "insufficient_reason": "SYNTHETIC: the report gives no prices or users.",
                                  "change": None, "significance": None, "main_uncertainty": None})
        self.assertEqual(row["content"]["economics"]["status"], "insufficient_evidence")
        with self.assertRaises(AccountsRefused):
            world.save(MOBILE, {**mobile(), "status": "insufficient_evidence", "insufficient_reason": "x"})


class WorkflowTest(unittest.TestCase):
    def assisted(self, world: World, **options) -> dict:
        batch, _ = news_batches.preview(world.desk, START, "assisted", actor="editor-1", **options)
        return batch

    def drafts(self, world: World, batch: dict, economics: dict) -> dict:
        found = news_views.world(world.desk, START)["stories"]
        return {"batch_id": batch["batch_id"], "drafts": [
            {"story_id": item["story_id"], "material_sha256": item["material_sha256"],
             "brief": {**world.brief(found[item["story_id"]]["reports"][0]["title"]),
                       "economics": with_report(economics[found[item["story_id"]]["reports"][0]["title"]],
                                                found[item["story_id"]]["material"]["reports"][0]["entry_id"])}}
            for item in batch["items"] if found[item["story_id"]]["reports"][0]["title"] in economics]}

    def test_any_eligible_story_follows_the_same_path_to_a_published_explanation(self):
        world = World(self)
        legacy = world.save(SALES, None)  # A published brief without an explanation.
        world.publish(world.story_id(SALES), legacy["version"])
        before = ns.state(world.desk.newsroom)["briefs"][world.story_id(SALES)]
        batch = self.assisted(world, story_ids=[world.story_id(SALES), world.story_id(GROWTH)], limit=5)
        actions = {item["story_id"]: item["action"] for item in batch["items"]}
        self.assertEqual(actions, {world.story_id(SALES): "explain", world.story_id(GROWTH): "prepare"})
        packet = news_batches.packet(world.desk, batch["batch_id"], START)
        self.assertIn("economic explanation", packet["rules"])
        self.assertEqual({note["id"] for note in packet["framework"]["notes"]},
                         set(econ_framework.framework()["notes"]))
        self.assertIsNotNone(next(item for item in packet["items"] if item["story_id"] == world.story_id(SALES))[
            "published_brief"])
        # Checking drafts saves and records nothing.
        planted = self.drafts(world, batch, {GROWTH: growth("percent_change")})
        files = every_file(world.root)
        checked = news_batches.import_drafts(world.desk, batch["batch_id"], planted, "SYNTHETIC assistant", None,
                                             "editor-1", world.clock, check=True)
        self.assertEqual(([row["outcome"] for row in checked["items"]], every_file(world.root)),
                         (["invalid_brief"], files))
        # A first import is refused (planted: a percent change of growth rates): recorded, shown as failed.
        done = news_batches.import_drafts(world.desk, batch["batch_id"], planted, "SYNTHETIC assistant", None,
                                          "editor-1", world.clock)
        self.assertEqual([row["outcome"] for row in done["items"]], ["invalid_brief"])
        failed = news_explanations.failures(world.desk.newsroom.path.parent)
        found = news_views.world(world.desk, START)
        self.assertEqual(news_explanations.state_of(found["folded"], found["stories"][world.story_id(GROWTH)], failed),
                         "failed")
        page = news_views.story_view(world.desk, world.story_id(GROWTH), START)
        self.assertEqual(page["explanation"]["state"], "failed")
        good = self.drafts(world, batch, {GROWTH: growth("difference"), SALES: sales(
            "SYNTHETIC: nominal sales were {c1} higher than in August.")})
        done = news_batches.import_drafts(world.desk, batch["batch_id"], good, "SYNTHETIC assistant", None,
                                          "editor-1", world.clock)
        self.assertEqual({row["outcome"] for row in done["items"]}, {"saved"})
        self.assertEqual(news_views.story_view(world.desk, world.story_id(GROWTH), START)["explanation"]["state"],
                         "drafted")
        published = news_batches.publish(world.desk, batch["batch_id"], {"reason": "SYNTHETIC", "reviewed": False},
                                          "editor-1", world.clock)
        self.assertEqual({row["outcome"] for row in published["items"]}, {"published"})
        page = news_views.story_view(world.desk, world.story_id(SALES), START)
        self.assertEqual((page["explanation"]["state"], page["brief"]["authorship"], page["brief"]["review"]["state"]),
                         ("ready", "ai_assistant", "not_reviewed"))
        shown = page["brief"]["economics"]
        self.assertEqual(shown["summary"]["what_changed"], "SYNTHETIC: retail sales were 745.0 billion dollars "
                                                           "(nominal) in September.")  # Its stated basis goes with it.
        self.assertEqual(shown["calculations"][0]["kind"], "derived")
        self.assertEqual([row["display"] for row in shown["figures"]][:2], ["745.0 billion dollars",
                                                                            "739.1 billion dollars"])
        # History is appended, never rewritten: the earlier version is exactly as it was.
        after = ns.state(world.desk.newsroom)["briefs"][world.story_id(SALES)]
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(after[-1]["based_on"], legacy["version"])
        self.assertEqual(after[-1]["preparation"]["analysis"]["context"], None)

    def test_a_backfill_is_bounded_newest_first_and_never_lists_a_story_outside_the_news(self):
        world = World(self)
        batch = self.assisted(world, backfill=True, limit=2)
        found = news_views.world(world.desk, START)
        listed = sorted((story for story in found["stories"].values() if story["relevance"]["state"] == "relevant"),
                        key=lambda story: (story["latest_at"], story["story_id"]), reverse=True)
        self.assertEqual([item["story_id"] for item in batch["items"]], [story["story_id"] for story in listed[:2]])
        self.assertEqual(batch["selection"], "backfill")
        self.assertNotIn(world.story_id(UNRELATED), [item["story_id"] for item in batch["items"]])
        unrelated = found["stories"][world.story_id(UNRELATED)]
        self.assertEqual(news_explanations.state_of(found["folded"], unrelated, {}), "not_listed")
        self.assertEqual(news_explanations.state_of(found["folded"], {**unrelated, "material": {
            **unrelated["material"], "reports": []}}, {}), "restricted")

    def test_a_new_material_or_method_makes_a_published_explanation_outdated(self):
        world = World(self)
        row = world.save(TARIFF, tariff_economics())
        world.publish(world.story_id(TARIFF), row["version"])
        page = lambda: news_views.story_view(world.desk, world.story_id(TARIFF), START)  # noqa: E731
        self.assertEqual(page()["explanation"]["state"], "ready")
        with mock.patch.object(story_economics, "ANALYSIS_VERSION", "econ-explanation-9.9"):
            self.assertEqual(page()["explanation"]["state"], "outdated")
        later = START + timedelta(hours=1)
        world.network.answers.update(trade_feeds(later, economics_items(later)))
        world.refresh(later)
        self.assertEqual(page()["explanation"]["state"], "outdated")
        self.assertIsNotNone(page()["brief"]["economics"])  # Still shown, with the brief's update note.

    def test_a_context_bundle_is_built_once_from_saved_records_and_recorded_with_the_version(self):
        world = World(self)
        found = news_views.world(world.desk, START)
        bundle, created = econ_context.build(world.desk, found, world.story_id(TARIFF), START, "editor-1",
                                             with_stories=[(world.story_id(RESPONSE), "SYNTHETIC: the response.")])
        again, created_again = econ_context.build(world.desk, found, world.story_id(TARIFF), START, "editor-1",
                                                  with_stories=[(world.story_id(RESPONSE), "SYNTHETIC: the response.")])
        self.assertEqual((created, created_again, again["bundle_id"]), (True, False, bundle["bundle_id"]))
        self.assertEqual({row["kind"] for row in bundle["items"]}, {"publication"})
        batch = self.assisted(world, story_ids=[world.story_id(TARIFF)], limit=1)
        self.assertEqual(batch["items"][0]["context"]["bundle_id"], bundle["bundle_id"])
        economics = tariff_economics()
        economics["alternatives"].append({"kind": "competing_explanation", "support": "event_evidence",
                                          "basis": ["context:p1"], "assumptions": [],
                                          "text": "SYNTHETIC: the Federation's response might matter more."})
        row = world.save(TARIFF, economics, bundle)
        self.assertEqual(row["preparation"]["analysis"]["context"]["bundle_id"], bundle["bundle_id"])
        self.assertEqual([item["item_id"] for item in row["content"]["economics"]["context"]], ["p1"])
        with self.assertRaises(AccountsRefused):  # A context item the bundle does not hold.
            economics["alternatives"][-1]["basis"] = ["context:p9"]
            world.save(TARIFF, economics, bundle)

    def test_reading_explanations_writes_and_requests_nothing(self):
        world = World(self)
        row = world.save(TARIFF, tariff_economics())
        world.publish(world.story_id(TARIFF), row["version"])
        before, requests = every_file(world.root), len(world.network.requests)
        news_views.story_view(world.desk, world.story_id(TARIFF), START)
        news_views.stories_view(world.desk, "hot", [], START)
        news_batches.coverage(world.desk, START)
        self.assertEqual((every_file(world.root), len(world.network.requests)), (before, requests))

    def test_a_paid_draft_carries_the_explanation_rules_and_is_checked_like_any_other(self):
        world = World(self, model=True)
        first = world.first(TARIFF)
        world.model.economics = lambda ids: with_report(tariff_economics(), first)
        batch, _ = news_batches.preview(world.desk, START, "model", story_ids=[world.story_id(TARIFF)], limit=1)
        self.assertEqual(world.model.requests, [])  # A preview sends nothing.
        folder = world.desk.newsroom.path.parent / "drafting"
        request = json.loads((folder / batch["items"][0]["draft"]["draft_id"] / "request.json").read_bytes())
        self.assertIn(brief_stages.STAGE_1_RULES, request["system"])  # The evidence, figures and calculations.
        self.assertNotIn("Framework notes", request["messages"][0]["content"])
        self.assertIn("figures", request["output_config"]["format"]["schema"]["properties"])
        self.assertEqual(batch["prompt_version"], brief_drafting.PROMPT_VERSION)
        second = both_stages(world.desk, batch, START, lambda sid: world.story(TARIFF), "admin-1", world.clock)
        request = json.loads((folder / second["items"][0]["draft"]["draft_id"] / "request.json").read_bytes())
        self.assertIn(brief_stages.STAGE_2_RULES, request["system"])  # The interpretation and the brief.
        self.assertIn("Framework notes", request["messages"][0]["content"])
        self.assertIn("channels", request["output_config"]["format"]["schema"]["properties"])
        row = ns.state(world.desk.newsroom)["briefs"][world.story_id(TARIFF)][-1]
        self.assertEqual((row["method"], row["content"]["economics"]["status"]), ("model", "explained"))
        self.assertEqual(row["preparation"]["analysis"]["framework_version"], econ_framework.FRAMEWORK_VERSION)


class ReaderTest(unittest.TestCase):
    def test_cards_say_who_prepared_a_brief_and_sources_have_distinct_names(self):
        world = World(self)
        row = world.save(TARIFF, tariff_economics())
        world.publish(world.story_id(TARIFF), row["version"])
        view = news_views.stories_view(world.desk, "latest", [], START)
        card = next(row for row in view["stories"] if row["story_id"] == world.story_id(TARIFF))
        self.assertEqual((card["brief"]["authorship"], card["brief"]["review"], card["brief"]["explained"]),
                         ("editor", "written_by_editor", True))
        names = [row["name"] for row in view["sources"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("U.S. Bureau of Labor Statistics: Consumer Price Index", names)
        self.assertEqual({row["source"] for row in view["sources"] if row["publisher"].startswith("U.S. Bureau of L")},
                         {"bls-cpi", "bls-empsit"})  # Identities unchanged.

    def test_the_page_keeps_facts_figures_calculations_reasoning_and_interpretation_apart(self):
        world = World(self)
        row = world.save(TARIFF, tariff_economics())
        world.publish(world.story_id(TARIFF), row["version"])
        shown = news_views.story_view(world.desk, world.story_id(TARIFF), START)["brief"]["economics"]
        self.assertEqual(shown["summary"]["who"], ["steel importers", "steel-using manufacturers"])
        self.assertEqual(shown["channels"][0]["kind"], "interpretation")
        self.assertEqual(shown["notes"][0]["kind"], "reasoning")
        self.assertEqual(shown["figures"][0]["kind"], "reported")
        self.assertTrue(all(source["url"].startswith("https://") for source in shown["notes"][0]["sources"]))
        self.assertNotIn("{f1}", json.dumps(shown))  # Rendered from the computed values.


class FrameworkTest(unittest.TestCase):
    def test_every_note_is_sourced_general_and_bound_to_instruments(self):
        found = econ_framework.framework()
        self.assertGreaterEqual(len(found["notes"]), 8)
        for note in found["notes"].values():
            self.assertTrue(note["sources"] and all(row["url"].startswith("https://") for row in note["sources"]))
            self.assertFalse(re.search(r"\d", note["mechanism"]), note["id"])
        bad = json.loads(econ_framework.PATH.read_text(encoding="utf-8"))
        bad["notes"][0]["mechanism"] += " Prices rose 12% in 2018."
        with self.assertRaises(econ_framework.FrameworkProblem):
            econ_framework.checked(bad)

    def test_no_story_has_its_own_code(self):
        """The explanation workflow names no story: no story ID, no headline, no demonstration list."""
        root = Path(story_economics.__file__).parent
        for name in ("story_economics.py", "econ_calc.py", "econ_context.py", "econ_framework.py", "econ_fidelity.py",
                     "brief_stages.py",
                     "news_explanations.py", "news_batches.py", "brief_drafting.py", "econ_framework.json"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"story-[0-9a-f]{16}", text), name)


class DirectionTest(unittest.TestCase):
    """econ-guard-0.2: a figure whose direction its quote contradicts, or does not establish, is never published."""

    def test_a_decline_quoted_as_a_magnitude_is_published_only_with_its_sign(self):
        world = World(self)
        quoted = "the bilateral trade has fallen by about 95 percent"
        world.network.answers.update(trade_feeds(START, economics_items(START) + [item(
            COURIER.link_host, "trade-fall", "SYNTHETIC trade falls", START - timedelta(hours=3),
            f"SYNTHETIC: {quoted}.")]))
        world.refresh(START)
        reports = news_reports.pool(world.desk.inbox, world.desk.feeds, world.desk.publishers)["reports"]
        news_stories.group(world.desk.newsroom, reports, set(), "setup", START, "group-key-0002")
        positive = explanation(figures=[figure("f1", 95, quoted, bound="approximate")],
                               significance={"basis": ["fact:1", "figure:f1"],
                                             "text": "SYNTHETIC: trade changed by {f1}."})
        self.assertIn("sign_contradicted", world.rules("SYNTHETIC trade falls", positive))
        negative = copy.deepcopy(positive)
        negative["figures"][0].update(value=-95, sign="from_words", sign_words="fallen by")
        self.assertEqual(world.rules("SYNTHETIC trade falls", negative), set())
        shown = world.save("SYNTHETIC trade falls", negative)["content"]["economics"]["figures"][0]
        self.assertEqual((shown["value"], shown["display"]), (-95, "about \u221295%"))

    def test_a_channel_says_what_supports_it_and_an_inference_states_its_bounds(self):
        world = World(self)
        bare = copy.deepcopy(tariff_economics())
        bare["channels"][0].update(support="bounded_inference", assumptions=[], note=None)
        with self.assertRaises(AccountsRefused) as refused:
            world.save(TARIFF, bare)
        self.assertIn("assumptions", str(refused.exception))
        unstated = copy.deepcopy(tariff_economics())
        unstated["channels"][0].update(support="event_evidence", basis=["figure:f1"])
        with self.assertRaises(AccountsRefused):  # A figure alone does not state a mechanism.
            world.save(TARIFF, unstated)
        noteless = copy.deepcopy(tariff_economics())
        noteless["channels"][0].update(note=None)
        with self.assertRaises(AccountsRefused):  # "framework" names its note.
            world.save(TARIFF, noteless)


class FrameworkHistoryTest(unittest.TestCase):
    """Reproduced 2026-10-26: after a framework note changed, a saved explanation showed the new wording and stayed
    "ready". An explanation keeps the notes it used; currentness follows the notes it used."""

    def published(self, world: World) -> None:
        row = world.save(TARIFF, tariff_economics())
        world.publish(world.story_id(TARIFF), row["version"])

    def read(self, world: World) -> dict:
        return news_views.story_view(world.desk, world.story_id(TARIFF), START)

    @staticmethod
    def edited(change) -> dict:
        found = copy.deepcopy(econ_framework.framework())
        change(found["notes"])
        found["framework_sha256"] = "9" * 64
        return found

    def test_a_revised_note_leaves_the_saved_explanation_as_it_was_and_makes_it_outdated(self):
        world = World(self)
        self.published(world)
        before = self.read(world)["brief"]["economics"]
        self.assertEqual(before["background"]["state"], "recorded")
        revised = self.edited(lambda notes: notes["tariff-pass-through"].update(mechanism="SYNTHETIC new wording."))
        with mock.patch.object(econ_framework, "framework", return_value=revised):
            page = self.read(world)
        self.assertEqual(page["brief"]["economics"]["notes"], before["notes"])  # The wording it was prepared with.
        self.assertEqual(page["explanation"]["state"], "outdated")
        self.assertIn("Import tariffs: who pays and who adjusts", page["explanation"]["reason"])

    def test_a_removed_note_still_reads_and_an_unrelated_revision_changes_nothing(self):
        world = World(self)
        self.published(world)
        before = self.read(world)
        removed = self.edited(lambda notes: notes.pop("tariff-pass-through"))
        with mock.patch.object(econ_framework, "framework", return_value=removed):
            page = self.read(world)
        self.assertEqual(page["brief"]["economics"]["notes"], before["brief"]["economics"]["notes"])
        self.assertEqual(page["explanation"]["state"], "outdated")
        other = self.edited(lambda notes: notes["electricity-shortages"].update(mechanism="SYNTHETIC elsewhere."))
        with mock.patch.object(econ_framework, "framework", return_value=other):
            page = self.read(world)
        self.assertEqual((page["explanation"]["state"], page["brief"]["economics"]), ("ready", before["brief"][
            "economics"]))

    def test_a_version_saved_before_snapshots_reads_its_archived_framework_or_says_it_cannot(self):
        world = World(self)
        self.published(world)
        story_id = world.story_id(TARIFF)
        folded = ns.state(world.desk.newsroom)
        brief = next(row for row in folded["briefs"][story_id] if "economics" in row["content"])
        legacy = copy.deepcopy(brief["content"]["economics"])
        legacy.pop("framework")
        archived = "7f9ec597b4ba8c824cf0fcc738bc557c76d863bb3d3762c86cfcf1bd8fd3be8a"  # econ-framework-0.1.
        view = story_economics.reader_view(legacy, brief["content"]["facts"], {"framework_sha256": archived})
        self.assertEqual(view["background"]["state"], "recovered")
        self.assertEqual(view["background"]["framework_version"], "econ-framework-0.1")
        self.assertIn("A tariff is a tax collected on covered imports", view["notes"][0]["mechanism"])
        lost = story_economics.reader_view(legacy, brief["content"]["facts"], {"framework_sha256": "8" * 64})
        self.assertEqual((lost["background"]["state"], lost["notes"]), ("unavailable", []))
        self.assertIn("cannot be recovered", lost["statement"])
        self.assertIn("not recoverable", lost["channels"][0]["note"]["title"])

    def test_every_framework_version_in_use_is_archived_under_its_own_hash(self):
        current = econ_framework.framework()
        self.assertIsNotNone(econ_framework.archived(current["framework_sha256"]))
        for path in econ_framework.ARCHIVE.glob("*.json"):
            with self.subTest(path=path.name):
                self.assertEqual(econ_framework.archived(path.stem)["framework_sha256"], path.stem)


if __name__ == "__main__":
    unittest.main()

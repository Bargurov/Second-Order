"""Financial-guarantee phrasing and append-only guard revalidation, over SYNTHETIC records; no provider calls."""
import copy
import json
import unittest
from unittest import mock

from second_order import brief_stages, newsroom_store as ns, story_briefs, story_economics
from second_order.accounts import AccountsRefused
from test_news_stories import GOOD, REVISION, START, World


CONDITIONAL = "The guarantee could lower perceived risk and help draw private capital, if projects prove bankable."


def content(implication=CONDITIONAL):
    return {**copy.deepcopy(GOOD), "implications": [{"text": implication}]}


class CertaintyTest(unittest.TestCase):
    def rules(self, sentence):
        return [row["rule"] for row in story_briefs.guard(content(sentence))["findings"]]

    def test_financial_nouns_and_credit_adjectives_are_not_certainty_claims(self):
        for sentence in (CONDITIONAL, "Loan guarantees may reduce financing risk.",
                         "The guarantees are capped and could help lenders.",
                         "Guaranteed loans might ease financing constraints.",
                         "Guaranteed loans to firms may ease financing constraints.",
                         "Guaranteed deposits could reduce funding risk."):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.rules(sentence), [])

    def test_guarantees_as_promises_and_other_certainty_words_still_stop_publication(self):
        for sentence in ("This guarantees higher investment, if the measure is adopted.",
                         "We guarantee that investment could rise.",
                         "Returns are guaranteed to increase, if the project proceeds.",
                         "Guaranteed profits could attract investors.",
                         "Guaranteed bond returns could attract investors.",
                         "Guaranteed loan growth might support lenders.",
                         "Investment might definitely increase.", "Prices could certainly fall."):
            with self.subTest(sentence=sentence):
                self.assertIn("certainty", self.rules(sentence))

    def test_a_financial_noun_does_not_mask_a_later_assertion_of_certainty(self):
        for sentence in ("The guarantee could help, but returns are guaranteed to increase.",
                         "The guarantee may lower risk and will certainly raise investment.",
                         "Loan guarantees could help, and this guarantees higher growth.",
                         "Guaranteed loans may help, but profits are guaranteed."):
            with self.subTest(sentence=sentence):
                self.assertIn("certainty", self.rules(sentence))

    def test_trade_causality_and_unhedged_checks_are_not_relaxed(self):
        for sentence, rule in (("The guarantee will lower financing costs.", "unhedged"),
                               ("The guarantee could help; investors should buy shares.", "advice"),
                               ("The guarantee could help because of the new policy.", "causal_claim"),
                               ("The guarantee may help investors buy shares.", "trade")):
            with self.subTest(sentence=sentence):
                self.assertIn(rule, self.rules(sentence))


class RevalidationTest(unittest.TestCase):
    def prepare(self, implication=CONDITIONAL, extra_findings=False):
        world = World(self)
        world.group()
        story = world.story_of(REVISION)
        report = story["material"]["reports"][0]["entry_id"]
        raw = {**content(implication), "facts": [{"text": "SYNTHETIC: an exemption was announced.",
                                                  "reports": [report]}]}
        # Readers already have version 1. The model's version 2 remains unpublished under the old guard.
        first, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": {**raw, "implications": [{"text": "The exemptions could matter if applied."}]},
            "method": "editorial", "based_on": None, "idempotency_key": "synthetic-first-0001"},
            story["material"], "synthetic-editor", START)
        story_briefs.publish(world.desk.newsroom, story["story_id"], {
            "version": first["version"], "reason": "SYNTHETIC earlier publication",
            "idempotency_key": "synthetic-publish-0001"}, "synthetic-editor", START)
        preparation = {"model": {"model": "SYNTHETIC", "draft_ids": ["synthetic-s1", "synthetic-s2"],
                                  "usage": {"input_tokens": 10, "output_tokens": 5}},
                       "cost": {"usage_cost": {"usd": 0.00007}}}
        basis = story_economics.evidence(story["material"])
        findings = []
        if extra_findings:
            raw["headline"] = "SYNTHETIC: 987654321 projects"
            preparation["model"]["stages_version"] = "SYNTHETIC-stages"
            findings = brief_stages.coherence(raw, basis)
        with mock.patch.object(story_briefs, "_certainty", story_briefs.CERTAIN.search), \
                mock.patch.object(story_briefs, "GUARD_VERSION", "brief-guard-0.1"):
            old, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
                "content": raw, "based_on": 1, "idempotency_key": "synthetic-model-0001"},
                story["material"], "synthetic-generator", START, method="model", preparation=preparation,
                findings=findings)
        self.assertFalse(old["publishable"])
        return world, story, raw, basis

    def rows(self, world, table):
        with world.desk.newsroom.reading() as con:
            return [dict(row) for row in con.execute("SELECT * FROM " + table)]

    def form(self, raw):
        return {"version": 2, "content": raw, "reason": "SYNTHETIC guard revalidation",
                "idempotency_key": "synthetic-revalidate-0001"}

    def revalidate(self, world, story, form, basis):
        return story_briefs.revalidate_version(world.desk.newsroom, story["story_id"], form, story["material"],
                                               "synthetic-revalidator", START, basis=basis)

    def test_appends_identical_content_preserves_generation_and_never_publishes_or_reviews(self):
        world, story, raw, basis = self.prepare()
        old_rows = self.rows(world, "briefs")
        publications, reviews = self.rows(world, "brief_publications"), self.rows(world, "brief_reviews")
        done, created = self.revalidate(world, story, self.form(raw), basis)
        self.assertTrue(created)
        self.assertEqual((done["version"], done["revalidated_from"], done["publishable"]), (3, 2, True))
        rows = self.rows(world, "briefs")
        self.assertEqual(rows[:2], old_rows)
        old, new = rows[1], rows[2]
        self.assertEqual((new["content"], new["content_sha256"], new["method"], new["based_on"]),
                         (old["content"], old["content_sha256"], "model", 2))
        self.assertEqual(json.loads(new["guard"])["findings"], [])
        self.assertEqual(json.loads(old["guard"])["guard_version"], "brief-guard-0.1")
        before, after = json.loads(old["preparation"]), json.loads(new["preparation"])
        self.assertEqual((after["model"], after["cost"]), (before["model"], before["cost"]))
        self.assertEqual(after["prepared_by"], "synthetic-revalidator")
        self.assertEqual(after["revalidation"]["previous_preparation_sha256"], ns.sha256_of(before))
        self.assertEqual(after["revalidation"]["additional_provider_requests"], 0)
        self.assertEqual(after["revalidation"]["additional_usage_cost_usd"], 0)
        self.assertEqual(self.rows(world, "brief_publications"), publications)
        self.assertEqual(self.rows(world, "brief_reviews"), reviews)
        self.assertEqual(self.revalidate(world, story, self.form(raw), basis), (done, False))
        self.assertEqual(self.rows(world, "briefs"), rows)

    def test_revalidation_refuses_changed_material_changed_content_and_missing_versions(self):
        world, story, raw, basis = self.prepare()
        before = self.rows(world, "briefs")
        with self.assertRaises(AccountsRefused) as refused:
            self.revalidate(world, {**story, "material": {**story["material"], "material_sha256": "0" * 64}},
                            self.form(raw), basis)
        self.assertEqual(refused.exception.code, "inputs_changed")
        with self.assertRaises(AccountsRefused) as refused:
            self.revalidate(world, story, self.form({**raw, "summary": "SYNTHETIC different text."}), basis)
        self.assertEqual(refused.exception.code, "content_changed")
        with self.assertRaises(AccountsRefused) as refused:
            self.revalidate(world, story, {**self.form(raw), "version": 999}, basis)
        self.assertEqual(refused.exception.code, "not_found")
        self.assertEqual(self.rows(world, "briefs"), before)

    def test_revalidation_retains_other_certainty_and_staged_coherence_stops(self):
        for sentence, extra, rule in (("The guarantee could certainly raise investment.", False, "certainty"),
                                       (CONDITIONAL, True, "unsourced_number")):
            with self.subTest(rule=rule):
                world, story, raw, basis = self.prepare(sentence, extra)
                done, _ = self.revalidate(world, story, self.form(raw), basis)
                self.assertFalse(done["publishable"])
                self.assertIn(rule, [row["rule"] for row in done["guard"]["findings"]])


if __name__ == "__main__":
    unittest.main()

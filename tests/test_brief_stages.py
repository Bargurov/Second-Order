"""Two-stage model drafts of a brief and its economic explanation (brief-stages-0.1, brief-drafting-0.2), over SYNTHETIC
stories and a simulated provider only: no external request is made. Passing these checks is offline evidence; it does
not show that the real provider accepts either format, nor that an explanation is economically right."""
import copy
import hashlib
import json
from pathlib import Path
from unittest import mock
import unittest

from second_order import (brief_claims, brief_contract, brief_drafting, brief_stages, brief_wire, econ_context,
                          econ_framework, news_explanations, news_views, newsroom_store as ns, output_schema,
                          story_briefs, story_economics)
from second_order.accounts import AccountsRefused
from second_order.model_draft import DraftRefused
from account_fakes import every_file
from news_desk_fakes import (RESPONSE, START, TARIFF, misfits, stage_replies, tariff_economics,
                             with_report)
from test_news_economics import World

ACTOR = "synthetic-editor"
# The rejected brief-prompt-8 format and the largest format the provider has accepted from this application
# (relevance-prompt-2), as measured on 2026-10-27
# (docs/news-brief-stages-2026-10-27.md (private; not in the public repository)).
REJECTED = {"objects": 15, "properties": 83, "arrays": 31, "bytes": 4758}
ACCEPTED = {"objects": 9, "properties": 29, "arrays": 8, "bytes": 2518}


def shape(schema: dict) -> dict:
    counts = {"objects": 0, "properties": 0, "arrays": 0, "choices": 0}

    def walk(node: dict) -> None:
        counts["choices"] += sum(1 for key in ("enum", "const", "anyOf", "oneOf", "allOf") if key in node)
        if node.get("type") == "object":
            counts["objects"] += 1
            counts["properties"] += len(node["properties"])
            assert node["additionalProperties"] is False and node["required"] == list(node["properties"])
            for child in node["properties"].values():
                walk(child)
        if node.get("type") == "array":
            counts["arrays"] += 1
            walk(node["items"])
    walk(schema)
    return {**counts, "bytes": len(json.dumps(schema, separators=(",", ":")))}


def form(view: dict) -> dict:
    return {"request_sha256": view["request_sha256"], "approve_paid_request": True,
            "estimated_max_usd": view["estimate"]["estimated_real_run_if_output_reaches_max_usd"]}


class Draft:
    """The SYNTHETIC tariff story (one report quoting a 15% tariff) with a simulated provider answering both stages
    from the SYNTHETIC tariff explanation."""

    def __init__(self, test: unittest.TestCase, economics=None):
        self.world = World(test, model=True)
        self.model = self.world.model
        self.report = self.world.first(TARIFF)
        self.story_id = self.world.story_id(TARIFF)
        self.model.economics = economics or (lambda ids: with_report(tariff_economics(), self.report))
        self.desk = self.world.desk

    def story(self) -> dict:
        return news_views.world(self.desk, START)["stories"][self.story_id]

    def story_now(self, story_id: str) -> dict:
        return news_views.world(self.desk, START)["stories"][story_id]

    def preview(self) -> dict:
        return brief_drafting.preview(self.desk, self.story())

    def approve(self, view: dict, **changes) -> tuple[dict, bool]:
        return brief_drafting.approve(self.desk, view["draft_id"], {**form(view), **changes}, self.story_now, ACTOR,
                                      self.world.clock)

    def folder(self, draft_id: str) -> Path:
        return self.desk.newsroom.path.parent / "drafting" / draft_id

    def versions(self) -> list[dict]:
        return ns.state(self.desk.newsroom)["briefs"].get(self.story_id, [])

    def evidence(self) -> dict:
        story = self.story()
        return story_economics.evidence(story["material"], self.desk.texts, None, story["first_at"])

    def run_first(self) -> dict:
        """Preview and approve stage 1; the workflow afterwards."""
        self.approve(self.preview())
        return self.preview()


class ContractTest(unittest.TestCase):
    def test_each_stage_format_is_materially_smaller_and_has_no_choices_unions_or_optional_fields(self):
        for stage in (1, 2):
            with self.subTest(stage=stage):
                found = shape(brief_stages.output_format(stage))
                self.assertEqual(found["choices"], 0)  # No enum, const or union reaches the provider's grammar.
                self.assertEqual(output_schema.problems(brief_stages.output_format(stage)), [])
                self.assertEqual(output_schema.profile(brief_stages.output_format(stage)),
                                 {"unions": 0, "nested_unions": 0, "optional": 0})
                self.assertLessEqual(found["properties"], REJECTED["properties"] // 2)
                self.assertLess(found["arrays"], REJECTED["arrays"] // 2)
                self.assertLess(found["objects"], ACCEPTED["objects"])
                self.assertLess(found["bytes"], ACCEPTED["bytes"])
        # The single request's format was rejected as REJECTED (brief-prompt-8); the assisted contract it was built
        # from has since gained what changed's form and respondents (econ-explanation-0.4), the claims record
        # (brief-assisted-3: a list of seven-field claims and each fact's claims) and an alternative's support and
        # assumptions (brief-assisted-4), and is never sent.
        self.assertEqual(shape(brief_wire.output_format(brief_drafting.SCHEMA)),
                         {"objects": REJECTED["objects"] + 1, "properties": REJECTED["properties"] + 2 + 9 + 2,
                          "arrays": REJECTED["arrays"] + 1 + 3 + 1, "bytes": 5436, "choices": 0})
        # brief-evidence-5 flattens each fact's claim into five texts to stay within this margin: 41 properties and
        # no new object or array (a separate claims list would have taken 44).
        self.assertEqual(shape(brief_stages.output_format(1))["properties"], REJECTED["properties"] // 2)

    def test_output_limits_cover_the_largest_permitted_reply_with_room_to_think(self):
        word = lambda count: "x" * count  # noqa: E731
        story = Draft(self).story()
        record = brief_drafting.largest(story["material"])
        ids = [letter * 40 for letter in "xyz"]  # Three reports a fact rests on; real report IDs have up to 40.
        refs = ["report:" + "x" * 41] * 8  # References of 48 characters, eight to a basis.
        figure = {"label": word(80), "value": -1234567.891, "unit": word(30), "measure": "growth_rate",
                  "period": word(60), "basis": "not_applicable", "seasonal": "not_seasonally_adjusted", "price": True,
                  "source": refs[0], "quote": word(300), "vintage_label": word(60), "sign_words": word(60),
                  "bound": "approximate", "statistic": "other_summary", "stock_flow": "flow_annual_rate"}
        claim = {"claim_holder": max(brief_claims.HOLDERS, key=len), "claim_holder_name": word(80),
                 "claim_modality": max(brief_claims.MODALITIES, key=len), "claim_quote": word(400),
                 "claim_condition": word(400)}  # brief-evidence-5: every fact records a claim of full size.
        first = {"insufficient_material": "", "facts": [{"text": word(300), "reports": ids, **claim}] * 6,
                 "themes": [{"kind": "company", "name": word(60), "basis": word(200)}] * 6,
                 "missing": [word(300)] * 5, "insufficient_evidence": "",
                 "change_stage": "implementation", "change_instrument": max(econ_framework.SUBJECTS, key=len),
                 "change_form": max(econ_framework.FORMS, key=len),
                 "change_respondents": max(econ_framework.RESPONDENTS, key=len),
                 "change_text": word(500), "change_basis": refs, "figures": [figure] * 8,
                 "calculations": [{"op": "percent_change", "inputs": ["f1", "f2"], "label": word(80)}] * 4}
        channel = {"scope": "micro", "support": "bounded_inference",
                   "note": max(econ_framework.framework()["notes"], key=len), "text": word(500),
                   "steps": [word(200)] * 5, "affected": [{"kind": "institutions", "name": word(80),
                                                           "how": word(200)}] * 5,
                   "conditions": word(200), "horizon": "quarters", "basis": refs}
        second = {"headline": word(160), "summary": word(700), "implications": [word(300)] * 3,
                  "uncertainties": [word(300)] * 5, "insufficient_explanation": "", "significance": word(500),
                  "significance_basis": refs, "main_uncertainty": word(200), "assumptions": [word(200)] * 5,
                  "channels": [channel] * 4,
                  "second_order": [{"from": "m1", "text": word(500), "conditions": word(200), "horizon": "quarters",
                                    "basis": refs}] * 3,
                  "alternatives": [{"kind": "competing_explanation", "support": "bounded_inference",
                                    "text": word(500), "basis": refs}] * 3,
                  "watch": [{"observable": word(80), "would": "weaken", "text": word(200)}] * 4}
        for stage, reply in ((1, first), (2, second)):
            with self.subTest(stage=stage):
                self.assertEqual(misfits(reply, brief_stages.output_format(stage)), [])
                size = len(json.dumps(reply, separators=(",", ":")))
                self.assertLessEqual(size, brief_stages.MAX_REPLY_CHARS[stage])
                self.assertGreaterEqual(brief_stages.MAX_TOKENS[stage] - size / 4, 2_000)  # Room to think.
                self.assertLess(brief_stages.MAX_TOKENS[stage], 12_000)  # Not the single request's whole allowance.
        self.assertEqual(record["status"], "explained")  # The planned estimate's largest first stage.

    def test_the_instructions_state_every_closed_choice_and_how_absence_is_written(self):
        expected = {1: ["proposal", "forecast", "import_tariff", "growth_rate", "seasonally_adjusted", "lower_bound",
                        "median", "flow_annual_rate", "stock_to_flow", "deflate", "sector", "survey_answers",
                        "announcement_or_decision", "not_stated", "net_percentage"],
                    # The framework notes are listed by each request for its own development (brief-explanation-3).
                    2: ["macro", "micro", "bounded_inference", "event_evidence", "quarters", "households",
                        "offsetting_force", "weaken", "assumption:aN",
                        "listed as applying to this story's subject, form of evidence and respondents"]}
        for stage, words in expected.items():
            system = brief_stages.system(stage)
            for word in words + ["case-sensitive", "exactly \"\"", brief_stages.STAGE_VERSIONS[stage],
                                 brief_stages.VERSION]:
                with self.subTest(stage=stage, word=word):
                    self.assertIn(word, system)
        self.assertNotIn("Framework notes", brief_drafting.material_text(
            Draft(self).story(), Draft(self).story()["material"], framework=False))

    def test_the_assisted_contract_is_unchanged(self):
        digest = hashlib.sha256((brief_drafting.SYSTEM + "|" + brief_drafting.ECONOMICS_RULES + "|" +
                                 json.dumps(brief_drafting.SCHEMA, sort_keys=True)).encode()).hexdigest()
        # Changed deliberately with econ-explanation-0.4 (form, respondents and net percentages), with
        # brief-assisted-3 (claims and the procedural stage, 29 October 2026), and with brief-assisted-4 (time and
        # scope as the evidence states them, a flow over another period, an alternative's support; same day), and with
        # brief-assisted-5 (how long a flow lasts, and no calculation of one whose length is not established;
        # econ-calc-0.5, same day), and with brief-assisted-6 (a claim holder's name exactly as the material writes it;
        # 1 November 2026, test_plain_names).
        self.assertEqual(brief_contract.ASSISTED_VERSION, "brief-assisted-6")
        self.assertEqual(digest, "1673c8b0aeadb631cda8c282cca58ced8871d0977b4d6dada76c06be269b7d86")


class AssemblyTest(unittest.TestCase):
    def content(self, draft: Draft) -> dict:
        story = draft.story()
        return {"headline": "SYNTHETIC tariff brief", "summary": "SYNTHETIC: the Synthetic Republic announced a tariff.",
                "facts": [{"text": "SYNTHETIC: a 15% tariff on imported steel was announced.",
                           "reports": [draft.report], "claims": ["k1"]}],
                # brief-evidence-5: the fact records whose plan the tariff is (brief_claims).
                "claims": [{"id": "k1", "holder": "other_party", "holder_name": "Synthetic Republic",
                            "modality": "prospective", "condition": None, "source": f"report:{draft.report}",
                            "quote": "The Synthetic Republic said on Monday it would impose a 15% tariff on imported "
                                     "steel from next month"}],
                "implications": [{"text": "SYNTHETIC: steel buyers could pay more if it applies."}], "themes": [],
                "uncertainties": ["SYNTHETIC: the products covered."], "missing": ["SYNTHETIC: the start date."],
                "economics": with_report(tariff_economics(), draft.report)} if story else None

    def stages(self, draft: Draft, content: dict) -> tuple[dict, dict]:
        first, second = stage_replies({**content, "insufficient_material": ""})
        return (brief_wire.decode(first, brief_stages.STAGE_1_SCHEMA),
                brief_wire.decode(second, brief_stages.stage_2_schema()))

    def test_a_full_explanation_round_trips_through_both_stages_into_the_same_content(self):
        draft = Draft(self)
        content = self.content(draft)
        first, second = self.stages(draft, content)
        record = brief_stages.foundations(first, draft.story()["material"], draft.evidence())
        self.assertEqual(record["status"], "explained")
        self.assertEqual(record["checked"]["figures"][0]["display"], "15%")  # Quoted and checked in stage 1.
        self.assertEqual(brief_stages.assemble(record, second), content)  # Deterministic; nothing filled in.
        self.assertEqual(brief_stages.coherence(content, draft.evidence()), [])

    def test_positions_number_the_items_and_assumptions_are_named_in_a_basis(self):
        draft = Draft(self)
        content = self.content(draft)
        first, second = self.stages(draft, content)
        self.assertNotIn("id", first["figures"][0])
        self.assertIn("assumption:a1", second["channels"][0]["basis"])
        record = brief_stages.foundations(first, draft.story()["material"], draft.evidence())
        assembled = brief_stages.assemble(record, second)["economics"]
        self.assertEqual([row["id"] for row in assembled["figures"]], ["f1"])
        self.assertEqual((assembled["channels"][0]["id"], assembled["channels"][0]["assumptions"],
                          assembled["second_order"][0]["id"]), ("m1", ["a1"], "s1"))
        self.assertNotIn("assumption:a1", assembled["channels"][0]["basis"])

    def test_first_stage_checks_quotes_signs_bounds_and_calculations_before_anything_follows(self):
        draft = Draft(self)
        content = self.content(draft)
        cases = {
            "quote": (lambda f: f["figures"][0].update(quote="SYNTHETIC words not in the report"), "not found"),
            "sign": (lambda f: f["figures"][0].update(value=-15), "a negative value needs sign from_words"),
            "calculation": (lambda f: f["calculations"].append({"op": "share", "inputs": ["f1", "f9"],
                                                                "label": "SYNTHETIC"}), "two of this explanation"),
            "change basis": (lambda f: f.update(change_basis=["figure:f1"]), "reported fact or report"),
            "placeholder": (lambda f: f.update(change_text="SYNTHETIC: {f2} applies."), "does not hold: f2"),
            "whitespace": (lambda f: f["figures"][0].update(vintage_label="  "), "either \"\" or text"),
            "half insufficient": (lambda f: f.update(insufficient_evidence="SYNTHETIC: thin."), "insufficient-evidence"),
        }
        for name, (alter, words) in cases.items():
            with self.subTest(name=name):
                first, _ = self.stages(draft, content)
                alter(first)
                with self.assertRaises(AccountsRefused) as refused:
                    brief_stages.foundations(first, draft.story()["material"], draft.evidence())
                self.assertIn(words, str(refused.exception))
        model_arithmetic = copy.deepcopy(self.stages(draft, content)[0])
        model_arithmetic["figures"][0].update(value=17.25, quote="a 15% tariff on imported steel")
        with self.assertRaises(AccountsRefused):  # A model's own number never becomes a figure.
            brief_stages.foundations(model_arithmetic, draft.story()["material"], draft.evidence())

    def test_an_insufficient_judgement_cannot_hide_content_and_no_field_may_be_dropped(self):
        draft = Draft(self)
        first, _ = stage_replies({**self.content(draft), "insufficient_material": ""})
        hiding = {**first, "insufficient_material": "SYNTHETIC: too little evidence"}
        with self.assertRaises(AccountsRefused) as refused:
            brief_stages.foundations(brief_wire.decode(hiding, brief_stages.STAGE_1_SCHEMA),
                                     draft.story()["material"], draft.evidence())
        self.assertIn("leaves every other text", str(refused.exception))
        for name in ("figures", "insufficient_evidence"):
            with self.subTest(dropped=name), self.assertRaisesRegex(DraftRefused, "missing fields"):
                brief_wire.decode({key: value for key, value in hiding.items() if key != name},
                                  brief_stages.STAGE_1_SCHEMA)
        with self.assertRaisesRegex(DraftRefused, "allowed choices"):  # Choices are checked locally.
            brief_wire.decode({**first, "change_stage": "Decision"}, brief_stages.STAGE_1_SCHEMA)
        with self.assertRaisesRegex(DraftRefused, "expected string"):  # Absence is "", never null.
            brief_wire.decode({**first, "change_text": None}, brief_stages.STAGE_1_SCHEMA)

    def test_the_second_stage_cannot_add_an_explanation_the_first_ruled_out_or_leave_one_half_empty(self):
        draft = Draft(self)
        content = self.content(draft)
        first, second = self.stages(draft, content)
        thin = {**first, "insufficient_evidence": "SYNTHETIC: no figures to explain.", "change_stage": "",
                "change_instrument": "", "change_form": "", "change_respondents": "", "change_text": "",
                "change_basis": [], "figures": [], "calculations": []}
        record = brief_stages.foundations(thin, draft.story()["material"], draft.evidence())
        self.assertEqual(record["status"], "insufficient_evidence")
        with self.assertRaises(AccountsRefused):
            brief_stages.assemble(record, second)
        brief_only = {**second, "significance": "", "significance_basis": [], "main_uncertainty": "",
                      "assumptions": [], "channels": [], "second_order": [], "alternatives": [], "watch": []}
        economics = brief_stages.assemble(record, brief_only)["economics"]
        self.assertEqual((economics["status"], economics["insufficient_reason"]),
                         ("insufficient_evidence", "SYNTHETIC: no figures to explain."))
        explained = brief_stages.foundations(first, draft.story()["material"], draft.evidence())
        with self.assertRaises(AccountsRefused):  # Giving up on the explanation leaves its fields empty.
            brief_stages.assemble(explained, {**second, "insufficient_explanation": "SYNTHETIC: no channel."})
        given_up = brief_stages.assemble(explained, {**brief_only, "insufficient_explanation": "SYNTHETIC: none."})
        self.assertEqual(given_up["economics"]["status"], "insufficient_evidence")
        self.assertEqual(given_up["facts"], content["facts"])  # The reported facts stay the first stage's.

    def test_numbers_and_placeholders_in_the_brief_texts_stop_publication(self):
        draft = Draft(self)
        content = self.content(draft)
        content["summary"] = "SYNTHETIC: a tariff of {f1} worth 9.5 billion was announced."
        rules = {row["rule"] for row in brief_stages.coherence(content, draft.evidence())}
        self.assertEqual(rules, {"placeholder_in_brief", "unsourced_number"})


class WorkflowTest(unittest.TestCase):
    def test_two_stages_make_one_unpublished_version_recording_each_stage(self):
        draft = Draft(self)
        view = draft.preview()
        self.assertEqual((view["state"], view["stage"], view["draft_id"][:9]), ("awaiting_stage_1", 1, "brief-s1-"))
        first, second = view["stages"]
        self.assertEqual((first["estimate_kind"], second["estimate_kind"]), ("exact", "planned"))
        self.assertIsNone(second["draft_id"])  # Its bytes depend on stage 1: nothing to approve yet.
        self.assertEqual(view["combined"]["planning_estimate_usd"], round(
            first["estimate"]["estimated_real_run_if_output_reaches_max_usd"] +
            second["estimate"]["estimated_real_run_if_output_reaches_max_usd"], 4))
        self.assertEqual(draft.model.requests, [])  # Previewing sends nothing.
        planned = second["estimate"]["estimated_real_run_if_output_reaches_max_usd"]
        done, sent = draft.approve(view)
        self.assertTrue(sent)
        self.assertEqual(done["attempt"]["state"], "validated")
        self.assertEqual(draft.model.requests, [(draft.folder(view["draft_id"]) / "request.json").read_bytes()])
        self.assertNotIn("Framework notes", json.loads(draft.model.requests[0])["messages"][0]["content"])
        self.assertEqual(draft.versions(), [])  # Stage 1 alone makes no version.
        self.assertEqual(done["next"]["stage"], 2)
        view = draft.preview()
        self.assertEqual((view["state"], view["draft_id"]), ("awaiting_stage_2", done["next"]["draft_id"]))
        exact = view["stages"][1]["estimate"]["estimated_real_run_if_output_reaches_max_usd"]
        self.assertLessEqual(exact, planned)  # The plan held the largest first stage.
        self.assertEqual(len(draft.model.requests), 1)  # Preparing stage 2 sent nothing.
        body = (draft.folder(view["draft_id"]) / "request.json").read_text(encoding="utf-8")
        user = json.loads(body)["messages"][0]["content"]
        self.assertIn("Publication text" if "Publication text" in user else "Excerpt:", user)  # The original evidence.
        self.assertIn("Framework notes", user)
        self.assertIn(f"First-stage foundations ({view['stages'][0]['draft_id']})", user)
        self.assertIn("They are a guide, not a source", user)
        record = json.loads((draft.folder(view["draft_id"]) / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual(record["foundations"]["foundations_sha256"], view["stages"][0]["foundations"]["sha256"])
        self.assertEqual((record["framework"], record["material_sha256"]),
                         (econ_framework.summary(), draft.story()["material"]["material_sha256"]))
        done, sent = draft.approve(view)
        self.assertEqual((sent, done["attempt"]["state"]), (True, "recorded"))
        self.assertEqual(draft.model.stages(), [1, 2])
        saved = draft.versions()[-1]
        self.assertEqual(saved["method"], "model")
        self.assertIsNone(draft.story()["brief"])  # Saved for the editors; readers see nothing until it is published.
        self.assertEqual(saved["content"]["economics"]["figures"][0]["display"], "15%")
        self.assertEqual(saved["guard"]["findings"], [])
        model, cost = saved["preparation"]["model"], saved["preparation"]["cost"]
        self.assertEqual(model["draft_ids"], [row["draft_id"] for row in view["stages"]])
        self.assertEqual([row["usage"] for row in model["stages"]], [{"input_tokens": 900, "output_tokens": 300}] * 2)
        self.assertEqual(model["usage"], {"input_tokens": 1800, "output_tokens": 600})
        self.assertEqual(cost["usage_cost"]["usd"], round(sum(row["usage_cost"]["usd"] for row in model["stages"]), 6))
        self.assertEqual(cost["estimated_max_usd"], round(sum(row["estimated_max_usd"] for row in model["stages"]), 4))
        final = draft.preview()
        self.assertEqual((final["state"], final["combined"]["remaining_planning_estimate_usd"]), ("complete", 0))
        self.assertEqual(len(draft.model.requests), 2)

    def test_a_first_stage_that_fails_or_finds_too_little_never_prepares_or_sends_the_second(self):
        cases = {
            "quote": ("invalid", lambda answer: answer["economics"]["figures"][0].update(quote="SYNTHETIC: not quoted")),
            "choice": ("invalid", lambda answer: answer["economics"]["change"].update(stage="invented")),
            "material": ("insufficient", lambda answer: answer.update(insufficient_material="SYNTHETIC: too little.")),
        }
        for name, (outcome, alter) in cases.items():
            with self.subTest(name=name):
                draft = Draft(self)
                draft.model.brief_reply = lambda answer, alter=alter: (alter(answer), answer)[1]
                done, _ = draft.approve(draft.preview())
                self.assertEqual(done["attempt"]["state"], outcome)
                self.assertNotIn("next", done)
                view = draft.preview()
                self.assertEqual(view["stages"][1]["draft_id"], None)
                self.assertFalse(any(path.name.startswith("brief-s2-") for path in draft.folder("x").parent.iterdir()))
                self.assertEqual(view["state"], "complete" if outcome == "insufficient" else "stopped")
                self.assertFalse(draft.approve(view)[1])  # Approving again sends nothing.
                self.assertEqual(draft.model.stages(), [1])
                self.assertEqual(draft.versions(), [])
                if outcome == "invalid":  # A refused reply keeps its reported usage.
                    outcome_file = json.loads((draft.folder(view["draft_id"]) / "outcome.json").read_text("utf-8"))
                    self.assertEqual(outcome_file["usage"], {"input_tokens": 900, "output_tokens": 300})
                else:
                    judged = ns.assessment(ns.state(draft.desk.newsroom), draft.story_id,
                                           draft.story()["material"]["material_sha256"])
                    self.assertEqual(judged["verdict"], "insufficient")
        draft = Draft(self)
        draft.model.stage_status = {1: 529}
        done, _ = draft.approve(draft.preview())
        self.assertEqual(done["attempt"]["state"], "provider_error")
        self.assertEqual(draft.preview()["state"], "stopped")
        self.assertEqual(draft.model.stages(), [1])

    def test_a_second_stage_that_fails_saves_no_version_and_keeps_the_validated_first(self):
        draft = Draft(self)
        view = draft.run_first()
        draft.model.stage_reply = {2: lambda reply: {**reply, "headline": ""}}
        done, sent = draft.approve(view)
        self.assertEqual((sent, done["attempt"]["state"]), (True, "invalid"))
        self.assertIn("The headline is text of 1 to 160 characters", done["attempt"]["detail"])
        self.assertEqual(draft.versions(), [])  # Nothing partial is saved or shown.
        outcome = json.loads((draft.folder(view["draft_id"]) / "outcome.json").read_text(encoding="utf-8"))
        self.assertEqual(outcome["usage"], {"input_tokens": 900, "output_tokens": 300})
        after = draft.preview()
        self.assertEqual((after["state"], after["stages"][0]["attempt"]["state"]), ("stopped", "validated"))
        self.assertIn("validated stage 1 is kept", after["detail"])
        self.assertFalse(draft.approve(view)[1])  # The same stage-2 bytes are never sent again.
        self.assertEqual(draft.model.stages(), [1, 2])
        failed = news_explanations.failures(draft.desk.newsroom.path.parent)[draft.story_id]
        self.assertEqual([row["source"] for row in failed], [view["draft_id"]])  # Shown as a failure, not dropped.

    def test_a_revised_second_stage_reuses_the_validated_first_without_sending_it_again(self):
        draft = Draft(self)
        view = draft.run_first()
        first_id = view["stages"][0]["draft_id"]
        draft.model.stage_status = {2: 400}
        draft.approve(view)
        draft.model.stage_status = {}
        revised = {**brief_stages.STAGE_VERSIONS, 2: "brief-explanation-synthetic-2"}
        with mock.patch.object(brief_stages, "STAGE_VERSIONS", revised):
            again = draft.preview()
            self.assertEqual((again["state"], again["stages"][0]["draft_id"]), ("awaiting_stage_2", first_id))
            self.assertNotEqual(again["draft_id"], view["draft_id"])  # A new request, from a revised contract.
            done, sent = draft.approve(again)
        self.assertEqual((sent, done["attempt"]["state"]), (True, "recorded"))
        self.assertEqual(draft.model.stages(), [1, 2, 2])  # Stage 1 was sent once.
        rows = draft.versions()[-1]["preparation"]["model"]["stages"]
        self.assertEqual([row["draft_id"] for row in rows], [first_id, again["draft_id"]])
        self.assertEqual(rows[0]["usage"], {"input_tokens": 900, "output_tokens": 300})  # Stage 1 counted once.

    def test_changed_inputs_invalidate_a_prepared_second_stage_before_anything_is_sent(self):
        draft = Draft(self)
        view = draft.run_first()
        changed = {"framework_version": "econ-framework-synthetic", "framework_sha256": "0" * 64}
        with mock.patch.object(econ_framework, "summary", lambda: changed):
            with self.assertRaises(AccountsRefused) as refused:
                draft.approve(view)
        self.assertEqual(refused.exception.code, "inputs_changed")
        self.assertFalse((draft.folder(view["draft_id"]) / "attempt.json").exists())
        foundations = draft.folder(view["stages"][0]["draft_id"]) / "foundations.json"
        kept = foundations.read_bytes()
        foundations.chmod(0o644)  # Saved records are read-only; this test alters one.
        foundations.write_bytes(kept.replace(b"SYNTHETIC", b"ALTERED"))
        with self.assertRaises(AccountsRefused) as refused:
            draft.approve(view)
        self.assertEqual(refused.exception.code, "inputs_changed")
        self.assertEqual(draft.preview()["state"], "stopped")  # Nothing is prepared from an altered record.
        foundations.write_bytes(kept)
        econ_context.build(draft.desk, news_views.world(draft.desk, START), draft.story_id, START, ACTOR,
                           with_stories=[(draft.world.story_id(RESPONSE), "SYNTHETIC: the other side's reply.")])
        with self.assertRaises(AccountsRefused) as refused:
            draft.approve(view)
        self.assertEqual(refused.exception.code, "inputs_changed")
        fresh = draft.preview()  # Context is a stage-1 input: a new first stage, approved on its own.
        self.assertEqual((fresh["state"], fresh["stage"]), ("awaiting_stage_1", 1))
        self.assertNotEqual(fresh["draft_id"], view["stages"][0]["draft_id"])
        self.assertEqual(draft.model.stages(), [1])

    def test_mismatched_repeated_interrupted_and_unknown_approvals_send_nothing_twice(self):
        draft = Draft(self)
        view = draft.preview()
        for changes in ({"request_sha256": "0" * 64}, {"estimated_max_usd": 0.01}, {"approve_paid_request": False}):
            with self.subTest(changes=changes), self.assertRaises(AccountsRefused) as refused:
                draft.approve(view, **changes)
            self.assertEqual(refused.exception.code, "approval_mismatch")
        self.assertFalse((draft.folder(view["draft_id"]) / "attempt.json").exists())
        for unknown in ("brief-s2-" + "0" * 16, "brief-s3-" + "0" * 16, "../brief-s1-" + "0" * 16):
            with self.subTest(unknown=unknown), self.assertRaises(AccountsRefused) as refused:
                brief_drafting.approve(draft.desk, unknown, form(view), draft.story_now, ACTOR, draft.world.clock)
            self.assertEqual(refused.exception.code, "not_found")
        self.assertTrue(draft.approve(view)[1])
        self.assertFalse(draft.approve(view)[1])  # A repeat returns the recorded attempt.
        second = draft.preview()
        folder = draft.folder(second["draft_id"])
        (folder / "attempt.json").write_text("{}", encoding="utf-8")  # Interrupted after the send started.
        (folder / "sent.json").write_text("{}", encoding="utf-8")
        done, sent = draft.approve(second)
        self.assertEqual((sent, done["attempt"]["state"]), (False, "sending"))
        self.assertEqual(draft.preview()["state"], "stopped")
        self.assertEqual(draft.model.stages(), [1])  # Each exact request at most once, ever.
        self.assertEqual(draft.versions(), [])

    def test_each_stage_shows_its_estimate_and_reported_usage(self):
        draft = Draft(self)
        view = draft.run_first()
        first, second = view["stages"]
        self.assertEqual((first["max_tokens"], second["max_tokens"]),
                         (brief_stages.MAX_TOKENS[1], brief_stages.MAX_TOKENS[2]))
        self.assertEqual(first["usage_cost"]["usd"], 0.0048)  # 900 input and 300 output tokens at $2 and $10.
        self.assertIsNone(second["usage_cost"])
        self.assertEqual(view["combined"]["usage_cost_usd"], 0.0048)
        self.assertEqual(view["combined"]["remaining_planning_estimate_usd"],
                         second["estimate"]["estimated_real_run_if_output_reaches_max_usd"])
        self.assertIn("not billing ceilings", view["combined"]["statement"])
        for row in (first, second):
            self.assertIn("A planning estimate, not a guaranteed billing ceiling", row["estimate"]["caveat"])
            self.assertEqual(row["estimate"]["output_tokens_at_max"], row["max_tokens"])

    def test_earlier_single_requests_and_their_outcomes_read_as_before_and_are_never_sent(self):
        draft = Draft(self)
        with mock.patch.object(brief_stages, "STAGE_VERSIONS", {1: "brief-evidence-0", 2: "brief-explanation-0"}):
            earlier = draft.preview()  # A stage request saved under an earlier stage contract.
        with self.assertRaises(AccountsRefused) as refused:
            draft.approve(earlier)
        self.assertEqual(refused.exception.code, "request_superseded")
        self.assertIn(f"brief-evidence-0, an earlier request contract than {brief_stages.STAGE_VERSIONS[1]}",
                      str(refused.exception))
        folder = draft.folder("brief-" + "a" * 16)
        folder.mkdir(parents=True)
        (folder / "preview.json").write_text(json.dumps({
            "drafting_version": "brief-drafting-0.1", "prompt_version": "brief-prompt-8", "draft_id": folder.name,
            "story_id": draft.story_id, "material_sha256": draft.story()["material"]["material_sha256"],
            "request_sha256": "a" * 64, "model": "claude-sonnet-5-5", "max_tokens": 12000}), encoding="utf-8")
        (folder / "request.json").write_bytes(b"{}")
        with self.assertRaises(AccountsRefused) as refused:
            brief_drafting.approve(draft.desk, folder.name, form({"request_sha256": "a" * 64, "estimate": {
                "estimated_real_run_if_output_reaches_max_usd": 0.1544}}), draft.story_now, ACTOR, draft.world.clock)
        self.assertEqual(refused.exception.code, "request_superseded")
        self.assertIn(f"brief-prompt-8, an earlier request contract than {brief_drafting.PROMPT_VERSION}",
                      str(refused.exception))
        (folder / "outcome.json").write_text(json.dumps({
            "outcome": "provider_error", "finished_at": "2026-10-27T10:44:17+00:00", "usage": None, "version": None,
            "detail": "The model provider returned HTTP 400 (invalid_request_error); no draft was produced"}),
            encoding="utf-8")
        state = brief_drafting.attempt_state(folder)
        self.assertEqual((state["state"], state["request_id"]), ("provider_error", None))
        failed = news_explanations.failures(draft.desk.newsroom.path.parent)[draft.story_id]
        self.assertEqual([row["source"] for row in failed], [folder.name])
        self.assertEqual(draft.model.requests, [])

    def test_reading_the_story_and_its_draft_records_sends_and_writes_nothing(self):
        draft = Draft(self)
        view = draft.run_first()
        draft.approve(view)
        before = every_file(draft.world.root)
        news_views.story_view(draft.desk, draft.story_id, START)
        news_views.stories_view(draft.desk, "hot", [], START)
        brief_drafting.preview(draft.desk, draft.story())  # Everything it would save is saved already.
        self.assertEqual(every_file(draft.world.root), before)
        self.assertEqual(draft.model.stages(), [1, 2])


if __name__ == "__main__":
    unittest.main()

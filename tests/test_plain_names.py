"""A claim holder's name as the material writes it, and plain text (brief-stages-0.8, brief-assisted-6,
econ-fidelity-0.6; docs/news-plain-names-2026-11-01.md (private; not in the public repository)).

The approved von der Leyen stage-1 trial of 29 October 2026
(docs/news-flow-stage-1-result-2026-10-29.md (private; not in the public repository)) was billed and refused: every claim
named its holder "Ursula von der Leyen", while the speech writes only "President von der Leyen", so the first name came from
the model, not the material. One fact also ended in "</br>", which no check stopped and which readers would see as written.

What these tests pin:

- The holder-name check stays strict: a name the evidence does not write is refused, however well known.
- The first stage's instructions (brief-evidence-8) and the assisted contract (brief-assisted-6) ask for the holder's
  name exactly as the material writes it, adding no first name, title or role, and the first stage asks for plain text.
  The first stage's format is the accepted one byte for byte; a request saved under brief-evidence-7 is superseded.
- econ-fidelity-0.6 stops publication of a text readers see that holds markup (an HTML-like tag). Claim quotes are the
  material's own words and are not read.

Whether a model follows the new wording is shown only by a sent request. Real cases: tests/consistency_cases.json
("quota") and the refused reply itself, cut to what that fixture holds; the rest is SYNTHETIC. Nothing reaches a
network, and passing these checks is not evidence that a brief is economically right."""
import copy
import unittest

from second_order import brief_claims, brief_contract, brief_drafting, brief_stages, brief_wire, econ_fidelity
from second_order.accounts import AccountsRefused
from test_econ_consistency import case, evidence, saved

REPORT = "ec-press:16bb242e2540d675e5d7"
QUOTA = ("We agreed an annual quota of 350 000 hybrid vehicles from China. Reducing exports by around 45%. This will be "
         "implemented through a safeguard, so we keep control.")
# The refused reply's third fact, as saved (data/newsroom/drafting/brief-s1-cc6ad4c83b70c59b/response.json).
REPLY_FACT = ("She announced a DiversifyEU package in December to help companies diversify supply chains, plus a new "
              "deterrence instrument and a solidarity package.</br>")


def claim(name: str) -> dict:
    return {"id": "k1", "holder": "speaker", "holder_name": name, "modality": "asserted", "quote": QUOTA,
            "condition": None, "source": f"report:{REPORT}"}


def reply(holder_name: str) -> dict:
    """The refused 29 October reply, cut to what the "quota" fixture holds (its first fact and claim, both figures, one
    theme and the sector), unchanged except for the holder name under test."""
    figure = {"basis": "not_applicable", "bound": "exact", "measure": "level", "price": False, "seasonal": "not_applicable",
              "sign_words": "", "source": f"report:{REPORT}", "statistic": "observed", "vintage_label": ""}
    return {
        "calculations": [], "change_basis": ["fact:1", "claim:k1", "figure:f1", "figure:f2"],
        "change_form": "statement", "change_instrument": "trade_flow", "change_respondents": "",
        "change_stage": "observation",
        "change_text": "In a speech to the European Parliament, von der Leyen stated that the EU and China agreed an "
                       "annual quota of {f1} hybrid vehicles, to be implemented through a safeguard.",
        "facts": [{"claim_condition": "", "claim_holder": "speaker", "claim_holder_name": holder_name,
                   "claim_modality": "asserted", "claim_quote": QUOTA, "reports": [REPORT],
                   "text": "Commission President von der Leyen said the EU agreed with China an annual quota of 350 000 "
                           "hybrid vehicles, reducing exports by around 45%, to be implemented through a safeguard."}],
        "figures": [{**figure, "label": "Annual quota on hybrid vehicles from China", "period": "annual",
                     "quote": "We agreed an annual quota of 350 000 hybrid vehicles from China.",
                     "stock_flow": "flow_per_year", "unit": "vehicles", "value": 350000},
                    {**figure, "basis": "not_stated", "seasonal": "not_stated",
                     "label": "EU trade deficit with China per day, 2025", "period": "2025",
                     "quote": "In 2025, our trade deficit with China reached €1 billion a day.",
                     "stock_flow": "flow_other_period", "unit": "billion euros", "value": 1}],
        "insufficient_evidence": "", "insufficient_material": "",
        "missing": ["Legal text, start date and details of the hybrid vehicle quota and safeguard"],
        "themes": [{"basis": "Quota on Chinese hybrid exports discussed in the speech.", "kind": "theme",
                    "name": "EU-China trade and trade defence"},
                   {"basis": "Hybrid vehicle quota with China.", "kind": "sector", "name": "Automotive"}]}


def first_stage(holder_name: str, version: str) -> dict:
    decoded = brief_wire.decode(copy.deepcopy(reply(holder_name)), brief_stages.STAGE_1_SCHEMAS[version])
    return brief_stages.foundations(decoded, {"reports": case("quota")["reports"]}, evidence("quota"), version)


def brief(**texts) -> dict:
    content = {"headline": "SYNTHETIC: a quota is agreed", "summary": "SYNTHETIC: the EU and China agreed a quota.",
               "facts": [{"text": "SYNTHETIC: a quota was agreed."}], "implications": [], "themes": [],
               "uncertainties": [], "missing": []}
    content.update(texts)
    return content


def markup(content: dict) -> list[tuple[str, str]]:
    return [(row["where"], row["matched"]) for row in econ_fidelity.findings(content, None)
            if row["rule"] == "markup_in_text"]


class HolderNameTest(unittest.TestCase):
    def test_a_first_name_the_material_does_not_write_is_refused(self):
        sources = evidence("quota")["sources"]
        with self.assertRaisesRegex(AccountsRefused, "holder_name “Ursula von der Leyen” is not named in the evidence"):
            brief_claims.checked([claim("Ursula von der Leyen")], sources)
        self.assertEqual(brief_claims.checked([claim("von der Leyen")], sources)[0]["holder_name"], "von der Leyen")

    def test_the_refused_reply_under_the_current_first_stage(self):
        with self.assertRaisesRegex(AccountsRefused, "holder_name “Ursula von der Leyen” is not named in the evidence"):
            first_stage("Ursula von der Leyen", brief_stages.STAGE_VERSIONS[1])
        found = first_stage("von der Leyen", brief_stages.STAGE_VERSIONS[1])
        self.assertEqual((found["status"], [row["value"] for row in found["figures"]], found["claims"][0]["holder_name"]),
                         ("explained", [350000, 1], "von der Leyen"))

    def test_the_first_stage_and_assisted_instructions_ask_for_the_name_as_written(self):
        for name, text in (("stage 1", brief_stages.system(1)), ("assisted", brief_contract.SYSTEM)):
            for words in ("exactly as the material writes it", "no first name, title or role"):
                with self.subTest(name, words=words):
                    self.assertIn(words, text)
        self.assertIn("plain text with no HTML or other markup", brief_stages.system(1))


class ContractTest(unittest.TestCase):
    def test_the_first_stage_format_is_unchanged_and_earlier_requests_are_superseded(self):
        self.assertEqual((brief_stages.VERSION, brief_stages.STAGE_VERSIONS, brief_drafting.PROMPT_VERSION,
                          brief_contract.ASSISTED_VERSION),
                         ("brief-stages-0.8", {1: "brief-evidence-8", 2: "brief-explanation-6"}, "brief-prompt-16",
                          "brief-assisted-6"))
        accepted = brief_stages.encoded(brief_wire.output_format(brief_stages.STAGE_1_SCHEMAS["brief-evidence-7"]))
        self.assertEqual(brief_stages.encoded(brief_stages.output_format(1)), accepted)
        self.assertEqual((brief_stages.ANALYSIS_OF["brief-evidence-7"], brief_stages.STAGES_OF["brief-evidence-7"]),
                         ("econ-explanation-0.6", "brief-stages-0.7"))
        # The consumed von der Leyen request follows an earlier contract now; it was never to be resent anyway.
        self.assertIn("earlier request contract than brief-evidence-8", brief_drafting.superseded(
            {"stage": 1, "stage_version": "brief-evidence-7", "stages_version": "brief-stages-0.7"}))

    def test_a_reply_to_the_earlier_contract_is_checked_as_it_was(self):
        with self.assertRaisesRegex(AccountsRefused, "holder_name “Ursula von der Leyen” is not named in the evidence"):
            first_stage("Ursula von der Leyen", "brief-evidence-7")


class MarkupTest(unittest.TestCase):
    def test_a_tag_in_a_text_readers_see_stops_publication(self):
        self.assertEqual(markup(brief(facts=[{"text": REPLY_FACT}])), [("facts[0]", "</br>")])
        self.assertEqual(markup(brief(headline="SYNTHETIC: a <b>quota</b> is agreed",
                                      missing=["SYNTHETIC: the legal text<br/>"])),
                         [("headline", "<b>"), ("missing[0]", "<br/>")])

    def test_comparisons_ampersands_and_angled_numbers_are_not_markup(self):
        self.assertEqual(markup(brief(summary="SYNTHETIC: growth <2% and inflation >3%; AT&T and P&G; x < y > z; "
                                              "a ratio of <0.5.")), [])

    def test_an_explanation_text_is_read_and_the_saved_quota_brief_has_none(self):
        content = saved("quota", 1)
        self.assertEqual(markup(content), [])
        content["economics"]["change"]["text"] += " <i>SYNTHETIC</i>"
        self.assertEqual(markup(content), [("economics.change", "<i>")])


if __name__ == "__main__":
    unittest.main()

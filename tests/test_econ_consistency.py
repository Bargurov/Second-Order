"""Time, prerequisites, stocks, flows and limits (econ-calc-0.4, econ-explanation-0.6, brief-stages-0.6;
docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)).

The two-stage trial of 29 October 2026 produced a model version 6 (rebuilt here on a fictional interview
about a new banknote series, case "northmere") which passed every automated check with two semantic errors: a channel
placed the 2027 trial after the decision on the withdrawal date, and an implication tested it "before any decision on
the withdrawal date", although the interview ties that decision to parliament and dates the trial separately; and an
alternative read the limit on exchanging old notes as a limit on how far they can be used, although the interview says
spending them is not limited and any surplus can be paid into an account. The audit of the same day found the
stock-or-flow record unable to type a flow over a half-year or over twelve months, so such flows were recorded as
neither.

What this slice changes, and what these tests pin:

- A level that is a flow over another or an unstated period is typed so (``flow_other_period``, econ-calc-0.4), shown
  to readers as a flow, and never combined with a level of another kind; earlier calculation versions are checked as
  they were. From econ-calc-0.5 (docs/news-flow-lengths-2026-10-29.md (private; not in the public repository)) flow totals are compared
  only over a length of time their kind establishes: such a flow is quoted and kept, and enters no difference, change or share (Codex
  reproduced a one-day total against a one-year total accepted under 0.4, which replays as it was).
- An alternative (a competing explanation or an offsetting force) states what supports it and the assumptions it rests
  on, as a channel does (econ-explanation-0.6): the inference from a holding limit to how much is used needs its
  mechanism, assumptions and support. Explanations saved earlier keep their shape and read as before.
- The two-stage contract (brief-stages-0.6) says which order in time the evidence establishes, that a requirement
  relates only what it names, that a mechanism's steps are not a timeline, and that a limit limits only what it names.
  The first stage's format is the one the provider accepted, byte for byte; the second stage's alternatives gain one
  typed field.

Real cases (tests/consistency_cases.json): our saved versions exactly and only the sentences of the European
Commission texts the tests need. The case "northmere" is FICTIONAL (marked "fictional": true: an invented central bank,
newspaper and speaker, example.org link), written to keep the structure of the audited interview without reusing its
authored text. SYNTHETIC variations are marked. Passing these checks is not evidence that an
explanation is right: whether a cited source states the mechanism claimed, whether an assumption holds and whether an
order of events is right are an editor's judgement, and the tests below assert those limits rather than hide them.
Nothing reaches a network."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from second_order import (brief_contract, brief_drafting, brief_stages, brief_wire, econ_calc, econ_classification,
                          economics_view, news_explanations, newsroom_store as ns, story_briefs, story_economics)
from second_order.accounts import AccountsRefused

CASES = json.loads(Path(__file__).with_name("consistency_cases.json").read_text(encoding="utf-8"))["cases"]
EARLIER = "econ-explanation-0.5"


def case(name: str) -> dict:
    return copy.deepcopy(CASES[name])


def evidence(name: str) -> dict:
    return story_economics.evidence({"reports": case(name)["reports"]}, None, None, case(name)["released_at"])


def source(name: str) -> str:
    return f"report:{case(name)['reports'][0]['entry_id']}"


def used(name: str) -> set[str]:
    return {row["entry_id"] for row in case(name)["reports"]}


def saved(name: str, version: int) -> dict:
    return case(name)["versions"][str(version)]["content"]


def raw(content: dict) -> dict:
    """A saved (checked) content in the shape a version is submitted in."""
    result = {key: copy.deepcopy(value) for key, value in content.items() if key != "economics"}
    economics = content["economics"]
    submitted = {key: copy.deepcopy(economics[key]) for key in story_economics.FIELDS}
    submitted["figures"] = [{**{key: row[key] for key in econ_calc.FIGURE_FIELDS - {"vintage_label"}},
                             "vintage_label": row["vintage"]["label"]} for row in economics["figures"]]
    submitted["calculations"] = [{key: row[key] for key in ("id", "op", "inputs", "label")}
                                 for row in economics["calculations"]]
    result["economics"] = submitted
    return result


def as_current(content: dict, supports: list[tuple[str, list[str]]]) -> dict:
    """A submitted 0.5 content in the 0.6 shape: each alternative with (support, assumptions) as given."""
    result = raw(content)
    for row, (support, assumed) in zip(result["economics"]["alternatives"], supports):
        row.update(support=support, assumptions=assumed)
    return result


def check(name: str, content: dict, version: str | None = None) -> dict:
    return story_briefs.checked_content(content, used(name), evidence(name), version)


def figure(name: str, figure_id: str, quote: str, value: float, unit: str, period: str, stock_flow: str,
           bound: str = "exact", label: str = "SYNTHETIC label") -> dict:
    return {"id": figure_id, "label": label, "value": value, "unit": unit, "measure": "level", "period": period,
            "basis": "not_stated", "seasonal": "not_applicable", "price": False, "source": source(name), "quote": quote,
            "vintage_label": None, "sign": "as_quoted", "sign_words": None, "bound": bound, "statistic": "observed",
            "stock_flow": stock_flow}


HALF_YEAR = "Our deficit with China reached almost 197 billion euros in the first half of this year."
RECORD = "the 2022 record of 397 billion euros"
EXPORTS = "Chinese hybrid electric vehicle exports to the EU had gone up from $2.5 billion to $7.5 billion."
A_DAY = "In 2025, our trade deficit with China reached €1 billion a day."
WORTH = "China has agreed to cut tariffs on EU products worth almost €4 billion."


class FlowOverAnotherPeriodTest(unittest.TestCase):
    """econ-calc-0.4: a flow over a half-year, a day or twelve months is a flow, not a level of no kind."""

    def test_a_half_year_flow_is_typed_as_a_flow_and_earlier_versions_are_checked_as_they_were(self):
        sources = evidence("deficit")["sources"]
        half = figure("deficit", "f1", HALF_YEAR, 197, "billion euros", "first half of 2026", "flow_other_period",
                      bound="upper_bound")
        kept = econ_calc.checked_figures([half], sources)
        self.assertEqual((kept[0]["stock_flow"], kept[0]["display"]), ("flow_other_period", "at most 197 billion euros"))
        self.assertEqual(economics_view.STOCK_FLOW_LABEL["flow_other_period"], "a flow over the period stated")
        for earlier in ("econ-calc-0.2", "econ-calc-0.3"):
            with self.subTest(earlier), self.assertRaisesRegex(AccountsRefused, "stock or flow"):
                econ_calc.checked_figures([half], sources, earlier)
        # What the deficit story saved (f1 typed as no kind) is still read as it was.
        self.assertEqual(saved("deficit", 5)["economics"]["figures"][0]["stock_flow"], "not_applicable")

    def test_a_flow_over_another_period_is_never_combined_with_a_level_of_another_kind(self):
        sources = evidence("deficit")["sources"]
        half = figure("deficit", "f1", HALF_YEAR, 197, "billion euros", "first half of 2026", "flow_other_period",
                      bound="upper_bound")
        year = figure("deficit", "f2", RECORD, 397, "billion euros", "2022", "flow_per_year")
        figures = {row["id"]: row for row in econ_calc.checked_figures([half, year], sources)}
        for op in ("difference", "percent_change", "share"):
            with self.subTest(op), self.assertRaisesRegex(AccountsRefused, "different stocks and flows"):
                econ_calc.computed([{"id": "c1", "op": op, "inputs": ["f2", "f1"], "label": "SYNTHETIC"}], figures)

    def test_the_gap_it_closes_two_levels_of_no_kind_combined_under_0_3(self):
        # The von der Leyen speech gives a deficit of €1 billion a day and products worth almost €4 billion. Recorded
        # as levels of no kind, as econ-calc-0.3 required of a day's flow, their percent change was computed; typed as
        # a flow over a day, it is refused.
        sources = evidence("quota")["sources"]
        day = figure("quota", "f1", A_DAY, 1, "billion euros", "a day in 2025", "not_applicable")
        worth = figure("quota", "f2", WORTH, 4, "billion euros", "as agreed", "not_applicable", bound="upper_bound")
        change = [{"id": "c1", "op": "percent_change", "inputs": ["f1", "f2"], "label": "SYNTHETIC"}]
        then = {row["id"]: row for row in econ_calc.checked_figures([day, worth], sources, "econ-calc-0.3")}
        self.assertEqual(econ_calc.computed(change, then, "econ-calc-0.3")[0]["value"], -75)
        now = {row["id"]: row for row in econ_calc.checked_figures(
            [{**day, "stock_flow": "flow_other_period"}, worth], sources)}
        with self.assertRaisesRegex(AccountsRefused, "different stocks and flows"):
            econ_calc.computed(change, now)

    def test_a_stock_is_set_only_against_a_flow_of_a_month_quarter_or_year(self):
        sources = {"report:synthetic": {"text": "SYNTHETIC: stocks of 60 units at the end of June; sales of 30 units "
                                                "in the first half.", "publisher": "Synthetic", "published": None,
                                        "kind": "report", "as_of": None}}
        rows = [{**figure("quota", "f1", "stocks of 60 units at the end of June", 60, "units", "first half", "stock"),
                 "source": "report:synthetic"},
                {**figure("quota", "f2", "sales of 30 units in the first half", 30, "units", "first half",
                          "flow_other_period"), "source": "report:synthetic"}]
        figures = {row["id"]: row for row in econ_calc.checked_figures(rows, sources)}
        with self.assertRaisesRegex(AccountsRefused, "month, quarter or year"):
            econ_calc.computed([{"id": "c1", "op": "stock_to_flow", "inputs": ["f1", "f2"], "label": "SYNTHETIC"}],
                               figures)


def synthetic(text: str) -> dict:
    return {"report:synthetic": {"text": text, "publisher": "Synthetic", "published": None, "kind": "report",
                                 "as_of": None}}


def flows(text: str, *rows: tuple, version: str = econ_calc.CALC_VERSION) -> dict:
    """SYNTHETIC levels quoted from ``text``, each (id, quote, value, unit, period, stock or flow), checked."""
    figures = [{**figure("quota", fid, quote, value, unit, period, kind), "source": "report:synthetic"}
               for fid, quote, value, unit, period, kind in rows]
    return {row["id"]: row for row in econ_calc.checked_figures(figures, synthetic(text), version)}


def calc(op: str, first: str, second: str, cid: str = "c1") -> dict:
    return {"id": cid, "op": op, "inputs": [first, second], "label": "SYNTHETIC"}


# Codex's reproduction against f9fa054 (data/local-checks/codex-econ-consistency-review-2026-10-29/
# unmatched-flow-periods.json): a one-day total and a one-year total, both typed as flows over another period.
ONE_DAY_ONE_YEAR = "SYNTHETIC: 3 billion euros on one day; 900 billion euros in a year."
DAY = ("f1", "3 billion euros on one day", 3, "billion euros", "one day", "flow_other_period")
YEAR = ("f2", "900 billion euros in a year", 900, "billion euros", "a year", "flow_other_period")
TWELVE_MONTHS = ("SYNTHETIC: exports were $7.5 billion in the twelve months to June 2026, against $2.5 billion in the "
                 "twelve months to June 2025.")
LATER = ("f1", "exports were $7.5 billion in the twelve months to June 2026", 7.5, "billion dollars",
         "twelve months to June 2026", "flow_per_year")
EARLIER_TOTAL = ("f2", "$2.5 billion in the twelve months to June 2025", 2.5, "billion dollars",
                 "twelve months to June 2025", "flow_per_year")


class FlowLengthTest(unittest.TestCase):
    """econ-calc-0.5: totals of flows are compared only over a length of time their kind establishes.

    A flow's kind states how long it lasts (a month, a quarter, a year, or a rate per year); its period states which
    dates it covers. A change between two totals needs the same length and naturally has different dates; a share needs
    one period, so the same dates. A flow over another or an unstated period has no established length: its figure is
    quoted and kept, and no calculation takes it. Nothing reads a length from a period's words, annualises a value or
    assumes a period the evidence does not state."""

    def test_flows_of_unequal_lengths_are_quoted_but_not_compared(self):
        figures = flows(ONE_DAY_ONE_YEAR, DAY, YEAR)
        self.assertEqual([(row["display"], row["period"], row["stock_flow"]) for row in figures.values()], [
            ("3 billion euros", "one day", "flow_other_period"), ("900 billion euros", "a year", "flow_other_period")])
        for op in ("difference", "percent_change"):
            with self.subTest(op), self.assertRaisesRegex(AccountsRefused, "lengths are not established"):
                econ_calc.computed([calc(op, "f2", "f1")], figures)
        # Typed as what it is, the year's total is a flow per year, and a day's flow is still not one.
        typed = flows(ONE_DAY_ONE_YEAR, DAY, (*YEAR[:5], "flow_per_year"))
        with self.assertRaisesRegex(AccountsRefused, "different stocks and flows"):
            econ_calc.computed([calc("percent_change", "f2", "f1")], typed)

    def test_unknown_lengths_stay_unknown_even_when_their_periods_read_alike(self):
        text = "SYNTHETIC: sales of 40 units; sales of 60 units."
        figures = flows(text, ("f1", "sales of 40 units", 40, "units", "not stated", "flow_other_period"),
                        ("f2", "sales of 60 units", 60, "units", "not stated", "flow_other_period"))
        for op in ("difference", "percent_change", "share"):
            with self.subTest(op), self.assertRaisesRegex(AccountsRefused, "lengths are not established"):
                econ_calc.computed([calc(op, "f1", "f2")], figures)

    def test_the_0_4_profile_replays_what_it_accepted(self):
        # Historical replay: under econ-calc-0.4 (f9fa054) the unmatched totals were compared, as Codex recorded.
        figures = flows(ONE_DAY_ONE_YEAR, DAY, YEAR, version="econ-calc-0.4")
        done = econ_calc.computed([calc("difference", "f2", "f1"), calc("percent_change", "f2", "f1", "c2")], figures,
                                  "econ-calc-0.4")
        keys = ("value", "unit", "measure", "decimals", "period", "bound", "formula", "display", "calc_version")
        self.assertEqual([{key: row[key] for key in keys} for row in done], [
            {"value": 897, "unit": "billion euros", "measure": "change", "decimals": 0,
             "period": "a year against one day", "bound": "exact", "formula": "f2 − f1",
             "display": "+897 billion euros", "calc_version": "econ-calc-0.4"},
            {"value": 29900.0, "unit": "percent", "measure": "growth_rate", "decimals": 1,
             "period": "a year against one day", "bound": "exact", "formula": "(f2 ÷ f1 − 1) × 100",
             "display": "+29,900.0%", "calc_version": "econ-calc-0.4"}])

    def test_growth_between_two_established_twelve_month_totals_compares_across_dates(self):
        figures = flows(TWELVE_MONTHS, LATER, EARLIER_TOTAL)
        done = econ_calc.computed([calc("percent_change", "f1", "f2"), calc("difference", "f1", "f2", "c2")], figures)
        self.assertEqual([(row["display"], row["period"], row["calc_version"]) for row in done], [
            ("+200.0%", "twelve months to June 2026 against twelve months to June 2025", "econ-calc-0.7"),
            ("+5.0 billion dollars", "twelve months to June 2026 against twelve months to June 2025",
             "econ-calc-0.7")])
        # The same holds for months, for rates per year and for stocks, whose dates differ in a comparison.
        cases = {"flow_per_month": ("September 2026", "September 2025"),
                 "flow_annual_rate": ("third quarter of 2026", "second quarter of 2026"),
                 "stock": ("end of June 2026", "end of June 2025")}
        for kind, (later, earlier) in cases.items():
            with self.subTest(kind):
                rows = flows("SYNTHETIC: 120 units; 100 units.", ("f1", "120 units", 120, "units", later, kind),
                             ("f2", "100 units", 100, "units", earlier, kind))
                self.assertEqual(econ_calc.computed([calc("percent_change", "f1", "f2")], rows)[0]["display"],
                                 "+20.0%")

    def test_a_share_is_of_one_period_of_established_length(self):
        text = "SYNTHETIC: exports of 30 billion euros to China; exports of 120 billion euros in all."
        part = ("f1", "exports of 30 billion euros to China", 30, "billion euros")
        whole = ("f2", "exports of 120 billion euros in all", 120, "billion euros")
        same = flows(text, (*part, "2025", "flow_per_year"), (*whole, "2025", "flow_per_year"))
        self.assertEqual(econ_calc.computed([calc("share", "f1", "f2")], same)[0]["display"], "25.0%")
        apart = flows(text, (*part, "2025", "flow_per_year"), (*whole, "2024", "flow_per_year"))
        with self.assertRaisesRegex(AccountsRefused, "same period"):
            econ_calc.computed([calc("share", "f1", "f2")], apart)
        # Refused although it may be right: identical words cannot tell a named half-year from an unstated period, and
        # the record holds no length for either (a stated limit; quote both figures instead).
        halves = flows(text, (*part, "first half of 2026", "flow_other_period"),
                       (*whole, "first half of 2026", "flow_other_period"))
        with self.assertRaisesRegex(AccountsRefused, "lengths are not established"):
            econ_calc.computed([calc("share", "f1", "f2")], halves)

    def test_a_stock_is_read_as_periods_of_a_flow_of_established_length(self):
        text = "SYNTHETIC: inventories of 60 units; sales of 30 units."
        stock = ("f1", "inventories of 60 units", 60, "units", "June 2026", "stock")
        month = flows(text, stock, ("f2", "sales of 30 units", 30, "units", "June 2026", "flow_per_month"))
        self.assertEqual(econ_calc.computed([calc("stock_to_flow", "f1", "f2")], month)[0]["display"], "2.00 months")
        other = flows(text, stock, ("f2", "sales of 30 units", 30, "units", "June 2026", "flow_other_period"))
        with self.assertRaisesRegex(AccountsRefused, "month, quarter or year"):
            econ_calc.computed([calc("stock_to_flow", "f1", "f2")], other)

    def test_the_speech_dates_its_two_totals_without_saying_how_long_each_lasts(self):
        # Von der Leyen: exports "had gone up from $2.5 billion to $7.5 billion. A threefold increase in just twelve
        # months." The twelve months separate the two figures; how long each total lasts is not stated. Typed so, the
        # figures are kept and no change is computed; the speaker's "threefold" stays her claim.
        sources = evidence("quota")["sources"]
        rows = [figure("quota", "f2", EXPORTS, 2.5, "billion dollars", "not stated (twelve months before f3)",
                       "flow_other_period"),
                figure("quota", "f3", EXPORTS, 7.5, "billion dollars", "not stated", "flow_other_period")]
        figures = {row["id"]: row for row in econ_calc.checked_figures(rows, sources)}
        self.assertEqual([row["display"] for row in figures.values()], ["2.5 billion dollars", "7.5 billion dollars"])
        with self.assertRaisesRegex(AccountsRefused, "lengths are not established"):
            econ_calc.computed([calc("percent_change", "f3", "f2")], figures)
        # What was saved (econ-explanation-0.3, econ-calc-0.2: both levels of no kind, +200%) reproduces as saved.
        content = saved("quota", 1)
        checked = check("quota", raw(content), "econ-explanation-0.3")
        self.assertEqual(ns.sha256_of(checked), case("quota")["versions"]["1"]["content_sha256"])
        self.assertEqual([(row["display"], row["calc_version"]) for row in checked["economics"]["calculations"]],
                         [("+200.0%", "econ-calc-0.2")])

    def test_the_calculation_profile_is_versioned_and_0_4_to_0_6_results_are_prepared_again(self):
        # econ-calc-0.6 (1 November 2026, docs/news-space-thousands-2026-11-01.md (private; not in the public repository)) reads "350
        # 000" as one number; econ-calc-0.7 (4 November 2026,
        # docs/news-number-boundaries-2026-11-04.md (private; not in the public repository)) also after a year and in a range.
        self.assertEqual(econ_calc.CALC_VERSION, "econ-calc-0.7")
        self.assertEqual(story_economics.ANALYSES, {
            "econ-explanation-0.3": "econ-calc-0.2", "econ-explanation-0.4": "econ-calc-0.3",
            "econ-explanation-0.5": "econ-calc-0.3", "econ-explanation-0.6": "econ-calc-0.7"})
        self.assertEqual(econ_calc.STOCK_FLOW_OF["econ-calc-0.4"], econ_calc.STOCK_FLOW_OF["econ-calc-0.5"])
        self.assertEqual(econ_calc.STOCK_FLOW_OF["econ-calc-0.5"], econ_calc.STOCK_FLOW_OF["econ-calc-0.6"])
        self.assertEqual(econ_calc.STOCK_FLOW_OF["econ-calc-0.6"], econ_calc.STOCK_FLOW_OF["econ-calc-0.7"])
        content = saved("northmere", 7)
        brief = lambda calc_version: {  # noqa: E731
            "content": content, "material_sha256": "m", "at": "2026-10-29T12:46:43+00:00",
            "preparation": {"analysis": {"calc_version": calc_version, "guard_version": "econ-guard-0.3",
                                         "framework_sha256": content["economics"]["framework"]["framework_sha256"],
                                         "context": None}}}
        # 0.3 could not type a flow over another period, so 0.5's rule cannot be shown to affect it; a 0.4 result may
        # hold a change between flows of unknown lengths, so it is prepared again (none was ever saved). A 0.5 result
        # may hold a figure read from "350 000" as 350, so it is prepared again too (none was ever saved); so may a 0.6
        # result, from "In 2025 350 000" or "350 000-400 000" (none was ever saved).
        self.assertEqual(news_explanations.reasons(brief("econ-calc-0.3"), "m"), [])
        for earlier in ("econ-calc-0.4", "econ-calc-0.5", "econ-calc-0.6"):
            self.assertEqual(news_explanations.reasons(brief(earlier), "m"), [
                f"it was prepared under an earlier calculation method ({earlier}; now econ-calc-0.7)"])

    def test_the_first_stage_and_assisted_instructions_say_how_long_a_flow_lasts(self):
        for name, text in (("stage 1", brief_stages.system(1)), ("assisted", brief_contract.ECONOMICS_RULES)):
            for words in ("any twelve consecutive months are a year", "the time between two figures",
                          "enters no calculation"):
                with self.subTest(name, words=words):
                    self.assertIn(words, text)
        self.assertNotIn("twelve months, a programme", brief_stages.system(1))


class AlternativeSupportTest(unittest.TestCase):
    """econ-explanation-0.6: an alternative is an interpretation like a channel and says what supports it."""

    def test_the_corrected_northmere_version_reads_as_saved_under_its_own_version(self):
        content = saved("northmere", 7)
        self.assertEqual(content["economics"]["analysis_version"], EARLIER)
        checked = check("northmere", raw(content), EARLIER)
        self.assertEqual(ns.sha256_of(checked), case("northmere")["versions"]["7"]["content_sha256"])
        view = economics_view.reader_view(checked["economics"], checked["facts"], None, checked["claims"])
        self.assertEqual(set(view["alternatives"][0]), {"kind", "label", "text", "basis"})

    def test_from_0_6_an_alternative_states_its_support_and_an_inference_its_assumptions(self):
        content = saved("northmere", 7)
        with self.assertRaisesRegex(AccountsRefused, "Alternative 1 has exactly"):
            check("northmere", raw(content))  # As saved under 0.5: no support.
        kept = check("northmere", as_current(content, [("event_evidence", []), ("event_evidence", [])]))
        self.assertEqual(kept["economics"]["analysis_version"], "econ-explanation-0.6")
        self.assertEqual([(row["support"], row["assumptions"]) for row in kept["economics"]["alternatives"]],
                         [("event_evidence", []), ("event_evidence", [])])
        refused = {
            "an inference without assumptions": ([("bounded_inference", []), ("event_evidence", [])],
                                                 "states the assumptions"),
            "an assumption the explanation does not hold": ([("bounded_inference", ["a9"]), ("event_evidence", [])],
                                                            "names only this explanation's assumptions"),
            "a support outside the list": ([("framework", []), ("event_evidence", [])], "what supports it"),
        }
        for label, (supports, words) in refused.items():
            with self.subTest(label), self.assertRaisesRegex(AccountsRefused, words):
                check("northmere", as_current(content, supports))
        bounded = check("northmere", as_current(content, [("bounded_inference", ["a1"]), ("event_evidence", [])]))
        self.assertEqual(bounded["economics"]["alternatives"][0]["assumptions"], ["a1"])

    def test_event_evidence_cites_the_fact_report_or_context_that_states_it(self):
        content = as_current(saved("northmere", 7), [("event_evidence", []), ("event_evidence", [])])
        content["economics"]["alternatives"][0]["basis"] = ["claim:k2"]
        with self.assertRaisesRegex(AccountsRefused, "cites the fact, report or context item"):
            check("northmere", content)

    def test_the_holding_limit_inference_needs_its_mechanism_and_the_limits_of_what_is_checked(self):
        model = saved("northmere", 6)
        wrong = model["economics"]["alternatives"][1]
        self.assertIn("Holding limits", wrong["text"])
        # As the model wrote it: no support, no assumption. Under 0.6 it is refused, and as an inference it must say
        # what it assumes.
        with self.assertRaisesRegex(AccountsRefused, "Alternative 1 has exactly"):
            check("northmere", raw(model))
        with self.assertRaisesRegex(AccountsRefused, "states the assumptions"):
            check("northmere", as_current(model, [("event_evidence", []), ("bounded_inference", [])]))
        # Limits, pinned. An assumption the interview contradicts is not detected ("spending old notes will stay
        # unrestricted"), and a cited fact that says the opposite of the claimed mechanism is not read: an editor's check.
        stated = as_current(model, [("event_evidence", []), ("bounded_inference", ["a3"])])
        stated["economics"]["assumptions"].append(
            {"id": "a3", "text": "SYNTHETIC: households can spend only as many old notes as the exchange limit allows."})
        self.assertEqual(check("northmere", stated)["economics"]["alternatives"][1]["assumptions"], ["a3"])
        cited = as_current(model, [("event_evidence", []), ("event_evidence", [])])
        self.assertEqual(check("northmere", cited)["economics"]["alternatives"][1]["basis"], ["fact:4", "claim:k4"])
        # A cap on the amount to exchange can still matter for the pace of an exchange: the inference is allowed when it
        # states its mechanism.
        adoption = as_current(model, [("event_evidence", []), ("bounded_inference", ["a3"])])
        adoption["economics"]["assumptions"].append(
            {"id": "a3", "text": "SYNTHETIC: some households would start exchanging later if the amount they may exchange is capped."})
        adoption["economics"]["alternatives"][1]["text"] = (
            "SYNTHETIC: if a monthly exchange limit made some households slower to start exchanging, the changeover "
            "could take longer; surplus above the limit could still be paid into a bank account.")
        self.assertEqual(check("northmere", adoption)["economics"]["alternatives"][1]["support"], "bounded_inference")

    def test_readers_see_what_supports_an_alternative_and_what_it_assumes(self):
        content = as_current(saved("northmere", 7), [("bounded_inference", ["a1"]), ("event_evidence", [])])
        kept = check("northmere", content)
        view = economics_view.reader_view(kept["economics"], kept["facts"], None, kept["claims"])
        first, second = view["alternatives"]
        self.assertEqual((first["support"], first["support_label"], first["assumptions"]),
                         ("bounded_inference", "An inference resting on stated assumptions", ["a1"]))
        self.assertEqual((second["support"], second["support_label"]),
                         ("event_evidence", "Stated in this story's sources"))

    def test_an_explanation_saved_under_0_5_is_read_as_current(self):
        content = saved("northmere", 7)
        brief = {"content": content, "material_sha256": "m", "at": "2026-10-29T12:46:43+00:00",
                 "preparation": {"analysis": {"calc_version": "econ-calc-0.3", "guard_version": "econ-guard-0.3",
                                              "framework_sha256": content["economics"]["framework"][
                                                  "framework_sha256"], "context": None}}}
        self.assertEqual(news_explanations.reasons(brief, "m"), [])
        self.assertIn(EARLIER, econ_classification.READ_AS_CURRENT["analysis"])
        self.assertIn("econ-calc-0.3", econ_classification.READ_AS_CURRENT["calculation"])


class StagesContractTest(unittest.TestCase):
    """brief-stages-0.6: the same first-stage format; one typed field more for an alternative."""

    def test_the_first_stage_format_sent_is_the_accepted_one_byte_for_byte(self):
        # brief-stages-0.7 (econ-calc-0.5): the first stage's instructions say how long a flow lasts; its format and the
        # second stage are unchanged. brief-stages-0.8 (1 November 2026, test_plain_names): names as written and plain
        # text, the same format again.
        self.assertEqual((brief_stages.VERSION, brief_stages.STAGE_VERSIONS),
                         ("brief-stages-0.8", {1: "brief-evidence-8", 2: "brief-explanation-6"}))
        accepted = brief_stages.encoded(brief_wire.output_format(brief_stages.STAGE_1_SCHEMAS["brief-evidence-5"]))
        self.assertEqual(brief_stages.encoded(brief_stages.output_format(1)), accepted)
        schemas = brief_stages.STAGE_1_SCHEMAS
        self.assertIs(schemas["brief-evidence-7"], schemas["brief-evidence-6"])
        self.assertIs(schemas["brief-evidence-8"], schemas["brief-evidence-7"])
        stock_flow = lambda version: brief_stages.STAGE_1_SCHEMAS[version]["properties"]["figures"]["items"][  # noqa
            "properties"]["stock_flow"]["enum"]
        self.assertIn("flow_other_period", stock_flow("brief-evidence-6"))
        self.assertNotIn("flow_other_period", stock_flow("brief-evidence-5"))
        self.assertEqual((brief_stages.ANALYSIS_OF["brief-evidence-5"], brief_stages.STAGES_OF["brief-evidence-5"]),
                         (EARLIER, "brief-stages-0.5"))
        self.assertEqual((brief_stages.ANALYSIS_OF["brief-evidence-6"], brief_stages.STAGES_OF["brief-evidence-6"]),
                         ("econ-explanation-0.6", "brief-stages-0.6"))
        self.assertEqual((brief_stages.ANALYSIS_OF["brief-evidence-7"], brief_stages.STAGES_OF["brief-evidence-7"]),
                         ("econ-explanation-0.6", "brief-stages-0.7"))
        # A request saved under f9fa054's first-stage instructions would be superseded, never sent (none was saved).
        self.assertIn("earlier request contract than brief-evidence-8", brief_drafting.superseded(
            {"stage": 1, "stage_version": "brief-evidence-6", "stages_version": "brief-stages-0.6"}))

    def test_the_second_stage_alternatives_gain_their_support_and_earlier_replies_decode_as_they_were(self):
        alternative = lambda version: brief_stages.stage_2_schema(version=version)["properties"]["alternatives"][  # noqa
            "items"]
        self.assertEqual(list(alternative("brief-explanation-6")["properties"]), ["kind", "support", "text", "basis"])
        for earlier in ("brief-explanation-1", "brief-explanation-5"):
            self.assertEqual(list(alternative(earlier)["properties"]), ["kind", "text", "basis"])
        # brief-explanation-5's format as the provider accepted it on 29 October 2026 (SHA-256 of its bytes then).
        sent = brief_stages.encoded(brief_wire.output_format(brief_stages.stage_2_schema(version="brief-explanation-5")))
        self.assertEqual(hashlib.sha256(sent).hexdigest(),
                         "8b3997eb5c0cb66dc6ce06047df83a11424137755f2232775a14e463bc605fcb")
        # brief-explanation-6 is that format with one string more in an alternative, and nothing else.
        without = copy.deepcopy(brief_stages.output_format(2))
        items = without["properties"]["alternatives"]["items"]
        self.assertEqual(items["properties"].pop("support"), {"type": "string"})
        items["required"].remove("support")
        self.assertEqual(brief_stages.encoded(without), sent)

    def test_assembly_keeps_each_contracts_alternatives(self):
        record = {"status": "explained", "facts": [{"text": "SYNTHETIC", "reports": ["r"], "claims": []}],
                  "claims": [], "themes": [], "missing": [], "change": {"stage": "observation"}, "figures": [],
                  "calculations": [], "checked": None}
        reply = {"headline": "SYNTHETIC", "summary": "SYNTHETIC", "implications": ["SYNTHETIC could"],
                 "uncertainties": [], "insufficient_explanation": "", "significance": "SYNTHETIC",
                 "significance_basis": ["fact:1"], "main_uncertainty": "SYNTHETIC", "assumptions": ["SYNTHETIC a1"],
                 "channels": [], "second_order": [], "watch": [],
                 "alternatives": [{"kind": "offsetting_force", "text": "SYNTHETIC may offset",
                                   "basis": ["fact:1", "assumption:a1"]}]}
        earlier = brief_stages.assemble(record, reply, "brief-explanation-5")
        self.assertEqual(earlier["economics"]["alternatives"], reply["alternatives"])
        reply["alternatives"][0]["support"] = "bounded_inference"
        current = brief_stages.assemble(record, reply)
        self.assertEqual(current["economics"]["alternatives"], [
            {"kind": "offsetting_force", "support": "bounded_inference", "text": "SYNTHETIC may offset",
             "basis": ["fact:1"], "assumptions": ["a1"]}])

    def test_the_instructions_keep_time_scope_and_support_apart(self):
        shared = ("only where the evidence states that order", "says nothing of when it happens",
                  "limits only what the evidence says it limits")
        for system in (brief_stages.system(1), brief_stages.system(2), brief_stages.BRIEF_ONLY_RULES):
            for words in shared:
                with self.subTest(words=words):
                    self.assertIn(words, system)
        self.assertIn("flow_other_period", brief_stages.system(1))
        self.assertIn("is its condition", brief_stages.system(1))
        for words in ("not a timeline", "an offsetting force is a mechanism", "account for how the material says"):
            with self.subTest(words=words):
                self.assertIn(words, brief_stages.system(2))


if __name__ == "__main__":
    unittest.main()

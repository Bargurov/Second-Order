"""Two-stage model drafts of a shared brief and its economic explanation (brief-stages-0.5).

The provider twice rejected the single brief request's output format: brief-prompt-7 and brief-prompt-8 returned HTTP
400 because "The compiled grammar is too large", the second time with no unions, enums or optional properties (83
properties in 15 objects and 31 arrays). Its structured-output documentation names flattening nested structures and
splitting into several requests as ways to reduce a schema's complexity. The largest format the provider has accepted
from this application is relevance-prompt-2's (29 properties in 9 objects and 8 arrays). So a brief and its explanation
are prepared in two focused requests, each with its own exact bytes, approval and outcome (brief_drafting):

1. Evidence and quantitative foundations (STAGE_1): the facts the reports state (each citing its reports), the
   sectors, companies or themes they name, what important information is missing, what changed (its stage, instrument,
   text and basis), the figures quoted exactly with their units, periods, bases, adjustments, bounds, statistics,
   signs and vintages, and the calculations the application is to compute, or the reason the material cannot support
   a brief, or the evidence an explanation. ``foundations`` checks it with the application's own checks (quotes in
   their sources, directions, bounds, comparability; calculations computed in code, never taken from the model)
   before anything more is prepared; a model's arithmetic never becomes a result.
2. Interpretation and reader text (STAGE_2): the headline, summary, implications and uncertainties, and the economic
   interpretation (significance, assumptions, channels with steps, affected parties, conditions and horizons,
   conditional second-order effects, alternatives and what to watch). Its request carries the same material, context
   items and framework notes as the evidence, then the checked first stage (``foundations_text``) as a guide that is
   not a source.

``assemble`` combines the two deterministically into the application's content shape; the version then passes every
check any version passes (story_briefs.checked_content, story_economics.checked, both guards) and ``coherence`` adds
publication stops for numbers or placeholders in the brief's texts that the evidence does not hold.

Neither output format has unions, enums or optional properties; nesting is flattened where a field holds one value
(what changed and why it matters are top-level fields; implications and assumptions are lists of texts). In the replies:

- every field is required; a text that does not apply is exactly "" (an empty string is never valid content, so it
  cannot be mistaken for a value); a list that does not apply is [];
- closed choices are stated in the instructions and checked here (brief_wire.decode), case-sensitive;
- figures, calculations, assumptions, channels and second-order effects are numbered by their position (f1, c1, a1,
  m1, s1, in the order given); a figure's sign is as written unless it gives the words that state its direction;
- a channel or second-order effect names the assumptions it rests on in its basis, as assumption:aN, beside fact:N,
  report:<ID>, figure:fN, calc:cN and context:<ID>.

Nothing is coerced or filled in: a missing or extra field, a wrong type, an unknown choice, whitespace standing for a
value, or explanation fields the first stage ruled out refuse the reply. Passing these checks does not show that the
provider accepts either format, nor that an explanation is economically right; only a sent request can show the first.

0.2 (brief-evidence-2, brief-explanation-2, brief-summary-2; after the fresh update of 28 October 2026,
docs/news-econ-fidelity-2026-10-28.md (private; not in the public repository)). Three request-contract weaknesses, each
reproduced from its saved reply:

- A scale word had no stated place: one reply gave 4900000 for "about 4.9 million Afghans" (refused only because the
  quote does not hold 4900000), while 4.9 in "people" would have passed, a millionfold error. Stage 1 now says that a
  value is the number as its quote writes it and that a scale word written after it belongs in the unit, and refuses a
  figure whose value, unit and quote disagree on scale (econ_fidelity.scale_problem) before any other check.
- A statistical release was classified by its form or by its subject at random (a firm survey of access to finance as
  credit conditions, a bank lending survey as an official statistic), and every framework note was offered as a choice:
  a reply named two notes that do not apply to an official statistic and was refused. A release whose subject is a
  listed kind now takes that kind with stage observation (a measurement, never a decision; a survey is never monetary
  policy), and a request lists only the framework notes that apply to its development's instrument.
- The second stage was told both "no {f1} in the brief's texts" and, unscoped, "in texts, write figures as {f1}", and
  saw the development only with its references: one summary copied "{f1} a year" and its version cannot be published.
  The brief's texts and the explanation's texts are now named apart, the development is also shown in words, and
  categories and inference stages are kept apart (durable goods are not capital goods; orders are not output).

A request saved under 0.1 is never sent; its records read and decode as before (``foundations`` takes the stage
version a reply was sent under, so an earlier refusal reproduces exactly).

0.3 (brief-evidence-3, brief-explanation-3;
docs/news-econ-form-subject-2026-10-28.md (private; not in the public repository)). The first stage classified a
development by one instrument that mixed the form of its evidence with its subject: an ECB bank lending survey was an
official statistic, refused the credit notes, while a classification by subject would have offered a note about firms'
answers. The first stage now gives the subject (change_instrument, without official_statistic), the form of the evidence
(change_form) and a survey's respondents (change_respondents), each only as the material states it ("unclear" when it does
not), and a survey's net percentage is its own measure (econ-calc-0.3); the request lists only the notes whose subjects,
forms and respondents all match (econ_classification), with their limits. The output format gains two string fields and no
choice reaches the provider's grammar; it has not been sent, so its acceptance is not shown. The second stage's format is
unchanged. Replies sent under brief-evidence-1 and -2 decode with their own format (STAGE_1_SCHEMAS) and are checked under
econ-explanation-0.3 (ANALYSIS_OF), as they were.

0.4 (brief-evidence-4, brief-explanation-4;
docs/news-net-balance-prose-2026-10-29.md (private; not in the public repository)). The first live brief-evidence-3 reply
(the ECB bank lending survey, 29 October 2026) typed its balances as net percentages, yet a theme read "Net demand for
housing loans fell by 27% net, driven by interest rates". Facts, themes, missing items and what changed are copied into
the brief unchanged, so a second stage cannot repair them, and the first stage's instructions said what a net percentage
is only for its figures. Both stages now say it for their texts (a balance stays respondents' answers, never the size of a
change, and a reason for it is credited to whoever gives it), and from brief-evidence-4 the first stage refuses a reply
whose own texts break it (econ_fidelity.balance_findings, the check publication applies to every text). The output formats
are unchanged, byte for byte: the provider accepted brief-evidence-3's live. A reply sent under an earlier first stage is
checked as it was (RETAINED_CHECKED), so its outcome reproduces; requests saved under 0.3 are superseded and never sent
(brief_drafting).

0.5 (brief-evidence-5, brief-explanation-5, brief-summary-3;
docs/news-claims-conditions-2026-10-29.md (private; not in the public repository), brief_claims). Published briefs lost
whose claim something was and on what condition: an interviewer's premise became an official's plan, an order's
conditional duty became "directs", a claimed effect and a scenario were shown as observed figures, and an opened
investigation was labelled as being put into effect. Each fact now records the claim it rests on, when its holder or force
matters: five text fields, each exactly "" when the fact rests on none (who says it, their name, how it is put, its exact
words in one of the fact's reports, and the words of a condition it states). The claim's source is the first report the
fact cites that holds its words, found by the application, never given by the model. Flattening the claim into its fact
keeps the format within the size margin below the rejected single request (41 properties, no new object or array; a
separate claims list would have taken 44); the application stores the claims as their own list (story-brief-0.4). A stage
``procedure`` is added (econ_classification). The first stage refuses a reply whose kept facts write a number the material
gives only inside such a claim without recording it (brief_claims.findings). The second stage's output format is
unchanged; its request lists the claims, and its instructions keep holders, conditions, bounds and scope. Replies to
earlier contracts decode with their own formats and are checked under the analysis version and stages version they were
sent under (STAGE_1_SCHEMAS, ANALYSIS_OF, STAGES_OF, all pinned), so every saved outcome reproduces; requests saved under
0.4 are superseded and never sent. Passing these checks offline does not show that the provider accepts the new format:
only a sent request can.

0.6 (brief-evidence-6, brief-explanation-6, brief-summary-4;
docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)). The first two-stage trial under 0.5 (29
October 2026) passed every check with two semantic errors: a channel's steps put a dated trial after the decision that was
to follow it and an implication tested it "before any decision", though the source ties the decision to separate
legislation and dates the trial itself; and an alternative read a limit on exchanging holdings as a limit on use, though
the source says use is not limited. All three contracts now say which order in time the evidence establishes (a
requirement relates only what it names; an unstated relationship stays unstated) and that a limit limits only what it
names (a stock is not a flow). The first stage records a requirement a claim states as its condition, keeps a limit with
what it limits, and may type a flow over another or an unstated period (econ-calc-0.4); its output format is
byte-identical to brief-evidence-5's, which the provider accepted, since choices are never sent. The second stage's steps
are the links of one mechanism, not a timeline (a prerequisite is a condition, a separately dated plan a fact), and each
alternative gains one typed field, what supports it, with its assumptions named in its basis (econ-explanation-0.6).
Earlier replies decode and assemble under their own contracts (STAGE_1_SCHEMAS, ``stage_2_schema(version=…)``,
``assemble(…, version)``) and are checked as they were; requests saved under 0.5 are superseded and never sent. Whether a
model keeps these distinctions is shown only by sent requests and an editor's reading: no check here reads an order of
events or what a limit applies to.

0.7 (brief-evidence-7; docs/news-flow-lengths-2026-10-29.md (private; not in the public repository)). econ-calc-0.5
refuses a difference, change or share of flows whose length their kind does not establish, so the first stage is told how
long a flow lasts (any twelve consecutive months are a year; the time between two figures is the length of neither) and
that a flow over another or an unstated period enters no calculation. Its format is brief-evidence-6's, byte for byte, and
its replies are checked under econ-explanation-0.6 as before; the second stage and the brief-only stage are unchanged.
Requests saved under 0.6 are superseded and never sent (none was saved).

0.8 (brief-evidence-8; docs/news-plain-names-2026-11-01.md (private; not in the public repository)). The approved 0.7
trial was billed and refused: every claim named its holder "Ursula von der Leyen", while the speech writes only "President
von der Leyen". The holder-name check stays as it was; the first stage is now told to write a holder's name exactly as the
material writes it, with no first name, title or role it does not write, and to write plain text with no markup (its reply
also ended a fact with "</br>", which econ-fidelity-0.6 now stops at publication). Its format is brief-evidence-7's, byte
for byte, and its replies are checked under econ-explanation-0.6 as before; the second stage and the brief-only stage are
unchanged. Requests saved under 0.7 are superseded and never sent (the only one was sent once and refused).
"""
import json

from . import (brief_claims, brief_wire, econ_calc, econ_classification, econ_fidelity, econ_framework,
               story_briefs, story_economics as se)
from .accounts import AccountsRefused
from .brief_rules import SHARED, STAGE_1_RULES, STAGE_2_RULES  # noqa: F401  (re-exported: the instructions)

VERSION = "brief-stages-0.8"
STAGE_VERSIONS = {1: "brief-evidence-8", 2: "brief-explanation-6"}
BRIEF_ONLY_VERSION = "brief-summary-4"
# First stages whose facts record the claims they rest on.
CLAIMED = ("brief-evidence-5", "brief-evidence-6", "brief-evidence-7", "brief-evidence-8")
# First stages whose figures are refused on a scale mismatch.
SCALE_CHECKED = ("brief-evidence-2", "brief-evidence-3", "brief-evidence-4", "brief-evidence-5", "brief-evidence-6",
                 "brief-evidence-7", "brief-evidence-8")
# First stages whose own texts are refused for a net percentage written as a change or given an unattributed reason,
# with the econ_fidelity rule each is checked with. brief-evidence-4 has only ever checked replies with 0.4 (no request
# or reply was saved under it while 0.3 was current); brief-evidence-5 also refuses a fact writing a number the
# material gives only inside a claim it does not record (brief_claims, econ-fidelity-0.5); brief-evidence-6, -7 and -8
# keep that rule (econ-fidelity-0.6 adds only a publication stop for markup, which refuses no first stage). Pinned by
# tests.
RETAINED_CHECKED = {"brief-evidence-4": "econ-fidelity-0.4", "brief-evidence-5": "econ-fidelity-0.5",
                    "brief-evidence-6": "econ-fidelity-0.5", "brief-evidence-7": "econ-fidelity-0.5",
                    "brief-evidence-8": "econ-fidelity-0.5"}
# The stages version each first-stage contract belongs to, recorded with a reply checked under it (so an earlier
# reply rechecked today reproduces its saved foundations exactly). Literal: never "the current version".
STAGES_OF = {"brief-evidence-1": "brief-stages-0.1", "brief-evidence-2": "brief-stages-0.2",
             "brief-evidence-3": "brief-stages-0.3", "brief-evidence-4": "brief-stages-0.4",
             "brief-evidence-5": "brief-stages-0.5", "brief-evidence-6": "brief-stages-0.6",
             "brief-evidence-7": "brief-stages-0.7", "brief-evidence-8": VERSION}
# The analysis version a first stage's reply is checked under: the one its contract was written for (literal).
ANALYSIS_OF = {"brief-evidence-1": "econ-explanation-0.3", "brief-evidence-2": "econ-explanation-0.3",
               "brief-evidence-3": "econ-explanation-0.4", "brief-evidence-4": "econ-explanation-0.4",
               "brief-evidence-5": "econ-explanation-0.5", "brief-evidence-6": "econ-explanation-0.6",
               "brief-evidence-7": "econ-explanation-0.6", "brief-evidence-8": se.ANALYSIS_VERSION}
# The second stages before brief-explanation-6, which all had one format: an alternative of kind, text and basis. From
# brief-explanation-6 an alternative also says what supports it (econ-explanation-0.6).
EARLIER_ALTERNATIVES = ("brief-explanation-1", "brief-explanation-2", "brief-explanation-3", "brief-explanation-4",
                        "brief-explanation-5")
NAMES = {1: "Evidence and figures", 2: "Interpretation and brief"}
DOES = {1: ("Extracts the reported facts, what changed, the quoted figures with their definitions and the "
            "calculations the application computes, or says the evidence is insufficient."),
        2: ("Writes the headline, summary, implications and uncertainties, and the economic interpretation, from the "
            "same sources and the checked first stage.")}
# Output limits (thinking and reply together). A reply filling every count and length limit of its stage (facts citing
# three reports, references of 48 characters) is at most MAX_REPLY_CHARS compact JSON characters
# (tests/test_brief_stages.py builds it): about 3,825 tokens for stage 1 (brief-evidence-3 added form and respondents)
# and 7,265 for stage 2 at four characters per token (brief-explanation-6 adds an alternative's support, 58 characters
# at most). Each limit leaves about 2,170 tokens or more beyond that for adaptive thinking at low effort; typical
# replies are far shorter. A reply cut at max_tokens is refused and never sent again. The single request this replaces
# had 12,000 tokens for both together, under 1,000 beyond the same largest replies.
MAX_TOKENS = {1: 8_000, 2: 9_500}  # brief-evidence-5: six facts may each carry a claim of up to ~900 characters.
MAX_REPLY_CHARS = {1: 21_300, 2: 29_100}
TEXT = {"type": "string"}
STRINGS = {"type": "array", "items": TEXT}
ENUM = lambda values: {"type": "string", "enum": list(values)}  # noqa: E731
OR_EMPTY = lambda values: {"type": "string", "enum": ["", *values]}  # noqa: E731  ("" where the choice does not apply)
ASSUMPTION = "assumption:"


def _object(**properties) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def _figure(measures: tuple, kinds: tuple = econ_calc.STOCK_FLOW) -> dict:
    return _object(label=TEXT, value={"type": "number"}, unit=TEXT, measure=ENUM(measures), period=TEXT,
                   basis=ENUM(econ_calc.BASES), seasonal=ENUM(econ_calc.SEASONAL), price={"type": "boolean"},
                   source=TEXT, quote=TEXT, vintage_label=TEXT, sign_words=TEXT, bound=ENUM(econ_calc.BOUNDS),
                   statistic=ENUM(econ_calc.STATISTICS), stock_flow=ENUM(kinds))


FIGURE = _figure(econ_calc.MEASURES)
FIGURE_03 = _figure(econ_calc.MEASURES, econ_calc.STOCK_FLOW_03)  # Up to brief-evidence-5 (econ-calc-0.3).
FACTS = {"type": "array", "items": _object(text=TEXT, reports=STRINGS)}
# brief-evidence-5: a fact and the claim it rests on, flat; every claim field is "" when it rests on none.
CLAIM_FIELDS = ("claim_holder", "claim_holder_name", "claim_modality", "claim_quote", "claim_condition")
CLAIMED_FACTS = {"type": "array", "items": _object(
    text=TEXT, reports=STRINGS, claim_holder=OR_EMPTY(brief_claims.HOLDERS), claim_holder_name=TEXT,
    claim_modality=OR_EMPTY(brief_claims.MODALITIES), claim_quote=TEXT, claim_condition=TEXT)}
THEMES = {"type": "array", "items": _object(kind=ENUM(story_briefs.THEME_KINDS), name=TEXT, basis=TEXT)}
CALCULATIONS = {"type": "array", "items": _object(op=ENUM(econ_calc.OPERATIONS), inputs=STRINGS, label=TEXT)}
STAGE_1_SCHEMA = _object(
    insufficient_material=TEXT, facts=CLAIMED_FACTS, themes=THEMES, missing=STRINGS, insufficient_evidence=TEXT,
    change_stage=OR_EMPTY(econ_classification.STAGES), change_instrument=OR_EMPTY(econ_framework.SUBJECTS),
    change_form=OR_EMPTY(econ_framework.FORMS), change_respondents=OR_EMPTY(econ_framework.RESPONDENTS),
    change_text=TEXT, change_basis=STRINGS, figures={"type": "array", "items": FIGURE}, calculations=CALCULATIONS)
# brief-evidence-5, as it was sent (the provider accepted it live on 29 October 2026): the same format, whose figures
# could not be a flow over another period (econ-calc-0.3). Choices are never sent, so the format's bytes are equal.
STAGE_1_SCHEMA_5 = _object(
    insufficient_material=TEXT, facts=CLAIMED_FACTS, themes=THEMES, missing=STRINGS, insufficient_evidence=TEXT,
    change_stage=OR_EMPTY(econ_classification.STAGES), change_instrument=OR_EMPTY(econ_framework.SUBJECTS),
    change_form=OR_EMPTY(econ_framework.FORMS), change_respondents=OR_EMPTY(econ_framework.RESPONDENTS),
    change_text=TEXT, change_basis=STRINGS, figures={"type": "array", "items": FIGURE_03}, calculations=CALCULATIONS)
# brief-evidence-3 and -4, as they were sent (the provider accepted them live on 29 October 2026): kept to decode
# replies, with the stages they offered.
STAGE_1_SCHEMA_4 = _object(
    insufficient_material=TEXT, facts=FACTS, themes=THEMES, missing=STRINGS, insufficient_evidence=TEXT,
    change_stage=OR_EMPTY(econ_classification.STAGES_04), change_instrument=OR_EMPTY(econ_framework.SUBJECTS),
    change_form=OR_EMPTY(econ_framework.FORMS), change_respondents=OR_EMPTY(econ_framework.RESPONDENTS),
    change_text=TEXT, change_basis=STRINGS, figures={"type": "array", "items": FIGURE_03}, calculations=CALCULATIONS)
# brief-evidence-1 and -2: one instrument (official_statistic included) and no net percentage; kept to decode replies.
LEGACY_STAGE_1_SCHEMA = _object(
    insufficient_material=TEXT, facts=FACTS, themes=THEMES, missing=STRINGS, insufficient_evidence=TEXT,
    change_stage=OR_EMPTY(econ_classification.STAGES_04), change_instrument=OR_EMPTY(econ_framework.INSTRUMENTS),
    change_text=TEXT, change_basis=STRINGS,
    figures={"type": "array", "items": _figure(econ_calc.MEASURES_OF["econ-calc-0.2"], econ_calc.STOCK_FLOW_03)},
    calculations=CALCULATIONS)
STAGE_1_SCHEMAS = {"brief-evidence-1": LEGACY_STAGE_1_SCHEMA, "brief-evidence-2": LEGACY_STAGE_1_SCHEMA,
                   "brief-evidence-3": STAGE_1_SCHEMA_4, "brief-evidence-4": STAGE_1_SCHEMA_4,
                   "brief-evidence-5": STAGE_1_SCHEMA_5, "brief-evidence-6": STAGE_1_SCHEMA,
                   "brief-evidence-7": STAGE_1_SCHEMA,  # 7: the same format; instructions say how long a flow lasts.
                   "brief-evidence-8": STAGE_1_SCHEMA}  # 8: the same format; names as written, plain text.

BRIEF_ONLY_SCHEMA = _object(headline=TEXT, summary=TEXT, implications=STRINGS, uncertainties=STRINGS)


def stage_2_schema(notes: list[str] | None = None, version: str = STAGE_VERSIONS[2]) -> dict:
    """The second stage's reply under ``version`` (the current contract unless given), with the framework notes a
    channel may name (today's, unless given). From brief-explanation-6 an alternative says what supports it."""
    notes = sorted(econ_framework.framework()["notes"]) if notes is None else notes
    alternative = _object(kind=ENUM(se.ALTERNATIVES), text=TEXT, basis=STRINGS) if version in EARLIER_ALTERNATIVES \
        else _object(kind=ENUM(se.ALTERNATIVES), support=ENUM(se.ALTERNATIVE_SUPPORTS), text=TEXT, basis=STRINGS)
    return _object(
        headline=TEXT, summary=TEXT, implications=STRINGS, uncertainties=STRINGS,
        insufficient_explanation=TEXT,
        significance=TEXT, significance_basis=STRINGS, main_uncertainty=TEXT, assumptions=STRINGS,
        channels={"type": "array", "items": _object(
            scope=ENUM(se.SCOPES), support=ENUM(se.SUPPORTS), note=OR_EMPTY(notes), text=TEXT, steps=STRINGS,
            affected={"type": "array", "items": _object(kind=ENUM(se.AFFECTED), name=TEXT, how=TEXT)},
            conditions=TEXT, horizon=ENUM(se.HORIZONS), basis=STRINGS)},
        second_order={"type": "array", "items": _object(**{"from": TEXT}, text=TEXT, conditions=TEXT,
                                                          horizon=ENUM(se.HORIZONS), basis=STRINGS)},
        alternatives={"type": "array", "items": alternative},
        watch={"type": "array", "items": _object(observable=TEXT, would=ENUM(se.WOULD), text=TEXT)})


def schema(stage: int) -> dict:
    return STAGE_1_SCHEMA if stage == 1 else stage_2_schema()


def output_format(stage: int) -> dict:
    """What the provider compiles: the stage's structure, with no enum, union, optional property or count limit."""
    return brief_wire.output_format(schema(stage))


def choices(value: dict) -> str:
    """Every closed choice of a reply, for its instructions (the format sent to the provider has none)."""
    found = []

    def walk(node: dict, path: str) -> None:
        if "enum" in node:
            allowed = [option for option in node["enum"] if option != ""]
            if not allowed:  # The framework notes, which each request lists for its own development.
                found.append(f"{path}: one of the framework notes listed as applying to this story's subject, form of "
                             "evidence and respondents (or \"\" where none applies).")
            else:
                found.append(f"{path}: {', '.join(allowed)}" + (" (or \"\" where it does not apply)"
                                                                 if "" in node["enum"] else "") + ".")
        for name, child in node.get("properties", {}).items():
            walk(child, f"{path}.{name}" if path else name)
        if "items" in node:
            walk(node["items"], path + "[]")

    walk(value, "")
    return " ".join(found)


def transport(stage: int) -> str:
    return (f"Transport contract {VERSION}, stage {stage} ({STAGE_VERSIONS[stage]}): reply with one JSON object in the "
            "exact structure of the output format. Every field is required. A text that does not apply is exactly "
            "\"\" and a list that does not apply is [], never null. Use exactly these allowed choices "
            "(case-sensitive; the application refuses any other value): " +
            choices(STAGE_1_SCHEMA if stage == 1 else stage_2_schema(notes=[])))


# ---------------------------------------------------------------- the instructions

# SHARED, STAGE_1_RULES and STAGE_2_RULES: brief_rules (re-exported above).


def system(stage: int) -> str:
    return f"{STAGE_1_RULES if stage == 1 else STAGE_2_RULES} {transport(stage)}"


BRIEF_ONLY_RULES = (
    "You write only a short shared news brief for Second Order. The validated first stage found enough material "
    "for a brief but insufficient evidence for an economic explanation; that decision is fixed. Use only the "
    "original sources and context given, with the first stage as a guide, never as another source. " + SHARED + " "
    "Reply with exactly four required fields: headline (at most 160 characters); summary (at most three sentences "
    "and 700 characters); implications (one to three texts, each at most 300 characters, conditional with may, "
    "might, could, would or if); uncertainties (at most five texts, each at most 300 characters). Credit the "
    "publisher's claims, state what was read and its limits, and do not invent numbers, causes, certainty or advice: "
    "write a number only as the material writes it, with what it is (an annual rate stays an annual rate, an estimate "
    "keeps its stated margin), never as {f1} or {c1}. Keep who says what as the first stage records it: never state "
    "a question as an answer, a conditional claim without its condition, a plan or scenario as an observed outcome, "
    "or a view as policy; never put in the headline a number the material gives only in a question, a condition or "
    "a view. "
    "Do not output an economic explanation, its reason, channels, figures or any additional field. The application "
    "retains the first stage's exact insufficient-evidence reason. "
    f"Transport contract {VERSION}, stage 2 ({BRIEF_ONLY_VERSION}): one JSON object in the exact output format; "
    "every field is required. Empty lists are [], never null. No JSON inside strings.")


# ---------------------------------------------------------------- stage 1: decode and check

def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_brief", detail)


def _absent(value: str, label: str) -> str | None:
    """None for exactly "", else the text; whitespace never stands for a value or for its absence."""
    if value == "":
        return None
    if not value.strip():
        raise _refuse(f"{label} is either \"\" or text.")
    return value


def _reason(value: str, label: str) -> str:
    if len(value) > se.LIMITS["reason"]:
        raise _refuse(f"{label} is at most {se.LIMITS['reason']} characters.")
    return " ".join(value.split())


def raw_figures(rows: list[dict]) -> list[dict]:
    """The first stage's figures in the explanation's shape, numbered by position (f1, f2, …); the sign is as quoted
    unless the figure gives the words that state its direction. Nothing else is changed or filled in."""
    figures = []
    for index, row in enumerate(rows, start=1):
        words = _absent(row["sign_words"], f"Figure {index}'s sign_words")
        figures.append({"id": f"f{index}", "label": row["label"], "value": row["value"], "unit": row["unit"],
                        "measure": row["measure"], "period": row["period"], "basis": row["basis"],
                        "seasonal": row["seasonal"], "price": row["price"], "source": row["source"],
                        "quote": row["quote"], "vintage_label": _absent(row["vintage_label"],
                                                                        f"Figure {index}'s vintage_label"),
                        "sign": "as_quoted" if words is None else "from_words", "sign_words": words,
                        "bound": row["bound"], "statistic": row["statistic"], "stock_flow": row["stock_flow"]})
    return figures


def _claimed_facts(rows: list[dict], found: dict) -> tuple[list[dict], list[dict]]:
    """brief-evidence-5: each fact and the claim it records, apart (claims k1, k2, … in the order of the facts that
    record one). A claim's source is the first report the fact cites that holds its words; nothing is filled in."""
    facts, claims = [], []
    for index, row in enumerate(rows, start=1):
        fact = {"text": row["text"], "reports": row["reports"], "claims": []}
        if row["claim_quote"] == "":
            if any(row[name] != "" for name in CLAIM_FIELDS):
                raise _refuse(f"Fact {index} records no claim (claim_quote is \"\"), so every claim field is \"\".")
            facts.append(fact)
            continue
        for name in ("claim_holder", "claim_holder_name", "claim_modality", "claim_quote"):
            _absent(row[name], f"Fact {index}'s {name}")
            if row[name] == "":
                raise _refuse(f"Fact {index}'s claim names its holder, the holder's name, its modality and its quote.")
        quote = econ_calc.normalized(row["claim_quote"])
        source = next((f"report:{entry}" for entry in row["reports"] if isinstance(entry, str) and quote in
                       econ_calc.normalized((found["sources"].get(f"report:{entry}") or {}).get("text", ""))), None)
        if source is None:
            raise _refuse(f"Fact {index}'s claim_quote is not in the reports the fact cites: a claim quotes its "
                          "source's exact words.")
        claim_id = f"k{len(claims) + 1}"
        claims.append({"id": claim_id, "holder": row["claim_holder"], "holder_name": row["claim_holder_name"],
                       "modality": row["claim_modality"], "quote": row["claim_quote"],
                       "condition": _absent(row["claim_condition"], f"Fact {index}'s claim_condition"),
                       "source": source})
        fact["claims"] = [claim_id]
        facts.append(fact)
    return facts, claims


def foundations(reply: dict, material: dict, found: dict, stage_version: str = STAGE_VERSIONS[1]) -> dict:
    """The first stage's decoded reply, checked: the record the second stage is prepared from (status explained,
    insufficient_evidence or insufficient_material). ``found`` is story_economics.evidence; ``stage_version`` the
    contract the reply was sent under (from brief-evidence-2, a figure whose value, unit and quote disagree on scale is
    refused first; from brief-evidence-3, what changed records its form and respondents; a reply to an earlier contract
    is checked as it was, under the analysis version it was written for). Refused otherwise."""
    classified = "change_form" in reply
    change_texts = ("change_stage", "change_instrument", "change_form", "change_respondents", "change_text") \
        if classified else ("change_stage", "change_instrument", "change_text")
    material_reason = _absent(reply["insufficient_material"], "insufficient_material")
    rest = ("facts", "themes", "missing", "change_basis", "figures", "calculations")
    if material_reason is not None:
        texts = ("insufficient_evidence", *change_texts)
        if any(reply[name] != [] for name in rest) or any(reply[name] != "" for name in texts):
            raise _refuse("An insufficient-material reply leaves every other text \"\" and every list [].")
        return {"stages_version": STAGES_OF[stage_version], "status": "insufficient_material",
                "reason": _reason(material_reason, "insufficient_material")}
    used = {row["entry_id"] for row in material["reports"]}
    claims = None
    if stage_version in CLAIMED:
        facts, claims = _claimed_facts(reply["facts"], found)
        claims = brief_claims.checked(claims, found["sources"])
        facts = story_briefs.checked_facts(facts, used, claims)
        stops = brief_claims.findings({"headline": "", "facts": facts, "claims": claims}, found["sources"])
        if stops:
            raise _refuse("These facts are kept in the brief unchanged, so a second stage cannot repair them: " +
                          "; ".join(f"{row['where']}: {row['detail']} (“{row['matched']}”)" for row in stops))
    else:
        facts = story_briefs.checked_facts(reply["facts"], used)
    themes = story_briefs.checked_themes(reply["themes"])
    missing = story_briefs.checked_items(reply["missing"], "missing", "Missing information")
    common = {"stages_version": STAGES_OF[stage_version], "facts": facts, "themes": themes, "missing": missing}
    if claims is not None:
        common["claims"] = claims
    evidence_reason = _absent(reply["insufficient_evidence"], "insufficient_evidence")
    if evidence_reason is not None:
        if any(reply[name] != "" for name in change_texts) or \
                any(reply[name] != [] for name in ("change_basis", "figures", "calculations")):
            raise _refuse("An insufficient-evidence reply gives no development, figures or calculations.")
        return {**common, "status": "insufficient_evidence",
                "reason": _reason(evidence_reason, "insufficient_evidence"), "change": None, "figures": [],
                "calculations": [], "checked": None}
    if stage_version in SCALE_CHECKED:
        for index, row in enumerate(reply["figures"], start=1):
            problem = econ_fidelity.scale_problem(row, f"Figure {index}")
            if problem:
                raise _refuse(problem)
    figures = raw_figures(reply["figures"])
    calculations = [{"id": f"c{index}", "op": row["op"], "inputs": row["inputs"], "label": row["label"]}
                    for index, row in enumerate(reply["calculations"], start=1)]
    change = {"stage": reply["change_stage"], "instrument": reply["change_instrument"]}
    if classified:
        change.update(form=reply["change_form"], respondents=_absent(reply["change_respondents"], "change_respondents"))
    change.update(text=reply["change_text"], basis=reply["change_basis"])
    base = se.foundations({"change": change, "figures": figures, "calculations": calculations}, facts, found,
                          ANALYSIS_OF[stage_version], claims)
    if stage_version in RETAINED_CHECKED:
        kept = [(f"facts[{index}]", row["text"]) for index, row in enumerate(facts)]
        kept += [(f"themes[{index}]", f"{row['name']} {row['basis']}") for index, row in enumerate(themes)]
        kept += [(f"missing[{index}]", row) for index, row in enumerate(missing)] + [("change", change["text"])]
        stops = econ_fidelity.balance_findings(kept, base["figures"] + base["calculations"])
        if stops:
            raise _refuse("These texts are kept in the brief unchanged, so a second stage cannot repair them: " +
                          "; ".join(f"{row['where']}: {row['detail']} (“{row['matched']}”)" for row in stops))
    return {**common, "status": "explained", "reason": None, "change": change, "figures": figures,
            "calculations": calculations,
            "checked": {"change": base["change"], "figures": base["figures"], "calculations": base["calculations"]}}


def directions(record: dict) -> list[str]:
    """The first stage's figures whose direction the guard would stop publication over, in words."""
    rows = []
    for row in (record.get("checked") or {}).get("figures", []):
        if row["direction_check"] == "contradicted":
            rows.append(f"{row['id']}: the quote describes a decline but the value is positive")
        elif row["direction_check"] == "unclear":
            rows.append(f"{row['id']}: the cited words do not establish its direction")
    return rows


# ---------------------------------------------------------------- stage 2: its input, decode and assembly

def _figure_line(row: dict) -> str:
    stock = "" if row["stock_flow"] == "not_applicable" else f"; {row['stock_flow'].replace('_', ' ')}"
    vintage = f"; vintage {row['vintage']['label']}" if row["vintage"]["label"] else ""
    sign = f"; direction from the words \"{row['sign_words']}\"" if row["sign"] == "from_words" else ""
    return (f"- {row['id']}: {row['label']} = {econ_calc.shown(row)} ({row['measure'].replace('_', ' ')}; "
            f"{row['period']}; {row['basis'].replace('_', ' ')}; {row['seasonal'].replace('_', ' ')}; statistic "
            f"{row['statistic'].replace('_', ' ')}{stock}; {row['bound'].replace('_', ' ')}"
            f"{'; a price measure' if row['price'] else ''}{sign}{vintage}; source {row['source']}). "
            f"Quote: \"{row['quote']}\"")


def foundations_text(record: dict, draft_id: str) -> str:
    """The checked first stage as the second stage's request states it, after the material."""
    lines = [f"First-stage foundations ({draft_id}): extracted by a model from the material above and checked by the "
             "application (each figure's quote was found in its source; each calculation was computed by the "
             "application). They are a guide, not a source: rely on the material above for anything you write.",
             "Facts (cite as fact:N):"]
    lines += [f"- fact:{index}: {row['text']} (reports: {', '.join(row['reports'])}"
              + (f"; rests on claim {', '.join(row['claims'])}" if row.get("claims") else "") + ")"
              for index, row in enumerate(record["facts"], start=1)]
    if record.get("claims") is not None:  # brief-evidence-5
        lines.append("Claims, who says what (cite as claim:kN, or the fact that records it; keep each holder, how it "
                     "was put and its condition):" if record["claims"] else "Claims: none recorded.")
        lines += [f"- claim:{row['id']}: {brief_claims.HOLDERS[row['holder']].lower()}, {row['holder_name']}; "
                  f"{brief_claims.MODALITIES[row['modality']].lower()}"
                  + (f"; condition \"{row['condition']}\"" if row["condition"] else "")
                  + f". Quote ({row['source']}): \"{row['quote']}\"" for row in record["claims"]]
    lines.append("Themes: " + ("; ".join(f"{row['kind']} {row['name']} ({row['basis']})" for row in record["themes"])
                               or "none."))
    lines.append("Missing information: " + ("; ".join(record["missing"]) or "none stated."))
    if record["status"] == "insufficient_evidence":
        lines.append(f"Economic evidence: insufficient for an explanation: {record['reason']} Write the brief only.")
        return "\n".join(lines)
    checked = record["checked"]
    change = checked["change"]
    lines.append(f"What changed: {change['text']} ({econ_classification.describe(change)}; "
                 f"basis {', '.join(change['basis'])})")
    rows = {row["id"]: row for row in checked["figures"] + checked["calculations"]}
    lines.append("What changed, in words (as readers see it; the brief writes each number as the material does): "
                 f"{econ_fidelity.render(change['text'], rows)}")
    lines.append("Figures (write as {fN}; cite as figure:fN):" if checked["figures"] else "Figures: none.")
    lines += [_figure_line(row) for row in checked["figures"]]
    lines.append("Calculations, computed by the application (write as {cN}; cite as calc:cN):"
                 if checked["calculations"] else "Calculations: none.")
    lines += [f"- {row['id']}: {row['label']} = {econ_calc.shown(row)} ({row['formula']}; {row['period']})"
              for row in checked["calculations"]]
    stops = directions(record)
    if stops:
        lines.append("Directions the application could not confirm (do not rely on these signs): " + "; ".join(stops))
    return "\n".join(lines)


def _refs(rows: list[str]) -> tuple[list[str], list[str]]:
    """(the evidence references, the assumptions named as assumption:aN) of a basis."""
    return ([ref for ref in rows if not ref.startswith(ASSUMPTION)],
            [ref[len(ASSUMPTION):] for ref in rows if ref.startswith(ASSUMPTION)])


EXPLANATION = ("significance", "main_uncertainty")
EXPLANATION_LISTS = ("significance_basis", "assumptions", "channels", "second_order", "alternatives", "watch")


def _insufficient(reason: str) -> dict:
    return {"status": "insufficient_evidence", "insufficient_reason": reason, "change": None, "significance": None,
            "main_uncertainty": None, "figures": [], "calculations": [], "assumptions": [], "channels": [],
            "second_order": [], "alternatives": [], "watch": []}


def assemble_brief_only(record: dict, reply: dict) -> dict:
    """A separate four-field contract; the first stage's insufficient-evidence decision is immutable."""
    if record["status"] != "insufficient_evidence" or set(reply) != set(BRIEF_ONLY_SCHEMA["properties"]):
        raise _refuse("The brief-only contract requires insufficient first-stage evidence and exactly four fields.")
    return _content(record, reply, _insufficient(record["reason"]))


def _content(record: dict, reply: dict, economics: dict) -> dict:
    content = {"headline": reply["headline"], "summary": reply["summary"], "facts": record["facts"],
               "implications": [{"text": text} for text in reply["implications"]], "themes": record["themes"],
               "uncertainties": reply["uncertainties"], "missing": record["missing"], "economics": economics}
    if record.get("claims") is not None:  # brief-evidence-5: the claims the facts record.
        content["claims"] = record["claims"]
    return content


def assemble(record: dict, reply: dict, version: str = STAGE_VERSIONS[2]) -> dict:
    """One brief with its explanation, in the application's content shape, from the checked first stage and the
    second stage's decoded reply under ``version`` (an earlier reply assembles as it did). Deterministic; it fills
    nothing in. The result still passes every content check when it is saved (story_briefs.add_version)."""
    if record["status"] not in ("explained", "insufficient_evidence"):
        raise _refuse("A brief is assembled only from a first stage that found material for one.")
    explanation_reason = _absent(reply["insufficient_explanation"], "insufficient_explanation")
    empty = all(reply[name] == "" for name in EXPLANATION) and all(reply[name] == [] for name in EXPLANATION_LISTS)
    if record["status"] == "insufficient_evidence":
        if explanation_reason is not None or not empty:
            raise _refuse("The first stage found the evidence insufficient for an explanation; the second stage gave "
                          "explanation fields.")
        economics = _insufficient(record["reason"])
    elif explanation_reason is not None:
        if not empty:
            raise _refuse("An insufficient explanation leaves the explanation's other texts \"\" and lists [].")
        economics = _insufficient(_reason(explanation_reason, "insufficient_explanation"))
    else:
        channels, effects = [], []
        for index, row in enumerate(reply["channels"], start=1):
            basis, assumed = _refs(row["basis"])
            channels.append({"id": f"m{index}", "scope": row["scope"], "support": row["support"],
                             "note": _absent(row["note"], f"Channel {index}'s note"), "text": row["text"],
                             "steps": row["steps"], "affected": row["affected"],
                             "conditions": _absent(row["conditions"], f"Channel {index}'s conditions"),
                             "horizon": row["horizon"], "basis": basis, "assumptions": assumed})
        for index, row in enumerate(reply["second_order"], start=1):
            basis, assumed = _refs(row["basis"])
            effects.append({"id": f"s{index}", "from": row["from"], "text": row["text"],
                            "conditions": row["conditions"], "horizon": row["horizon"], "basis": basis,
                            "assumptions": assumed})
        alternatives = reply["alternatives"]  # Up to brief-explanation-5: kind, text and basis, as given.
        if version not in EARLIER_ALTERNATIVES:
            alternatives = []
            for row in reply["alternatives"]:
                basis, assumed = _refs(row["basis"])
                alternatives.append({"kind": row["kind"], "support": row["support"], "text": row["text"],
                                     "basis": basis, "assumptions": assumed})
        economics = {"status": "explained", "insufficient_reason": None, "change": record["change"],
                     "significance": {"text": reply["significance"], "basis": reply["significance_basis"]},
                     "main_uncertainty": reply["main_uncertainty"], "figures": record["figures"],
                     "calculations": record["calculations"],
                     "assumptions": [{"id": f"a{index}", "text": text}
                                     for index, text in enumerate(reply["assumptions"], start=1)],
                     "channels": channels, "second_order": effects, "alternatives": alternatives,
                     "watch": reply["watch"]}
    return _content(record, reply, economics)


def coherence(content: dict, found: dict) -> list[dict]:
    """Publication stops for the brief's own texts in a two-stage draft (brief-stages-0.1): a number the evidence does
    not hold (a model's arithmetic, or a figure from memory), or a {f1} placeholder, which is rendered only in the
    explanation. Words and numbers, not truth."""
    rows = []
    places = [("headline", content["headline"]), ("summary", content["summary"])]
    places += [(f"facts[{index}]", row["text"]) for index, row in enumerate(content["facts"])]
    places += [(f"implications[{index}]", row["text"]) for index, row in enumerate(content["implications"])]
    places += [(f"themes[{index}]", f"{row['name']} {row['basis']}") for index, row in enumerate(content["themes"])]
    places += [(f"uncertainties[{index}]", row) for index, row in enumerate(content["uncertainties"])]
    places += [(f"missing[{index}]", row) for index, row in enumerate(content["missing"])]
    for where, text in places:
        names = econ_calc.placeholders(text)
        if names:
            rows.append({"where": where, "rule": "placeholder_in_brief", "matched": "{" + names[0] + "}",
                         "detail": econ_fidelity.PLACEHOLDER_IN_BRIEF})
        for number, _ in econ_calc.numbers(econ_calc.PLACEHOLDER.sub(" ", text)):
            if round(number, 9) not in found["numbers"]:
                rows.append({"where": where, "rule": "unsourced_number", "matched": f"{number:g}",
                             "detail": "A number in the brief is one the evidence states; this one is not in it."})
                break
    return rows


def encoded(value: object) -> bytes:
    """A request body as it is saved and sent: compact JSON, sorted keys, UTF-8."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

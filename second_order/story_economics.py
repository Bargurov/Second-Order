"""A story's economic explanation (econ-explanation-0.6), part of its shared brief from story-brief-0.3.

A brief says what was reported; its explanation says why the development may matter economically, from the same
evidence and nothing else. It is prepared before anyone reads it, by the brief's own workflow (an assisted batch, or a
model draft after a visible cost decision), and kept in the brief's append-only versions with what it was prepared from.

The explanation keeps four kinds of statement apart, and readers are told which is which:

- **Reported facts** are the brief's facts and the material's reports (``fact:N``, ``report:<entry ID>``).
- **Figures** are quoted from the evidence with their units, periods, nominal or real basis, seasonal adjustment and
  vintage; **derived calculations** are computed in code (econ_calc), never written by a drafter (``figure:f1``,
  ``calc:c1``; texts show them by placeholders, {f1} and {c1}).
- **General economic reasoning** is a framework note (econ_framework): a sourced mechanism that applies to the
  development's instrument, never evidence about the event.
- **Conditional interpretations** are the channels through which the development may work (macro or micro, with the
  intermediate steps, who may be affected, the conditions and the horizon), the possible second-order effects (each
  following from a channel, with its own conditions), competing explanations and offsetting forces, and what to watch
  that would support or weaken the reading. Each rests on cited evidence and on assumptions stated as such.

What changed is classified by stage (a proposal, a decision, its implementation, an observation or a forecast) and by
instrument; for a proposal or a forecast every channel and effect states the condition under which it would follow.
An explanation may say that the evidence is insufficient instead, with the reason.

``checked`` refuses an explanation that its evidence cannot hold: a reference to nothing, a figure its quote does not
hold, a calculation of things that do not compare, a mechanism that does not apply to the instrument, a second-order
effect without a channel or a condition. ``findings`` (econ-guard-0.1) are lexical and numeric checks that stop
publication: a number found nowhere in the evidence, a surprise without a contemporaneous expectations benchmark, a
"real" reading of a nominal figure, a level presented as a change, a historical comparison without its evidence, a
named company the evidence does not name, a security price forecast, advice, a causal or certain claim. They check words
and numbers, not economics: passing them is not evidence that an explanation is right (docs/economic-review-rubric.md).

0.2 (2026-10-26, after an economic review of the first published explanations):
- Figures keep their direction, bound, summary statistic and stock or flow (econ-calc-0.2); a figure whose direction
  the quote contradicts or does not establish stops publication (econ-guard-0.2), instead of being read either way.
- Every channel says what supports it: a sourced framework note that applies to the instrument (``framework``), the
  event's own sources stating the mechanism (``event_evidence``, citing a fact, report or context item), or an
  inference bounded by stated assumptions and conditions (``bounded_inference``); readers are told which.
- The explanation keeps a snapshot of the exact framework notes it used (econ_framework.snapshot), so it reads the same
  after a note is revised or removed. One saved before snapshots existed is read with the archived framework that has
  its recorded SHA-256, or says that its background cannot be recovered.

0.3 (econ-context-0.2): a cited context item keeps its role (evidence on this development, a comparison, methodology
or a benchmark), why it is relevant, when it was retrieved and its timing against the story's first report. What
happened never rests on context published after the story was first reported (econ-guard-0.3,
``retrospective_as_event``); such later context may support other parts and is labelled wherever it is shown.
``context_statement`` says precisely what was read beyond the story's own material: passages are passages, not the
whole publication.

Reader rendering (econ-fidelity-0.1, 2026-10-28; presentation only, so the analysis version is unchanged): every text
writes a figure or calculation with the qualifiers its stated metadata gives (an annual rate, a seasonal adjustment, a
stated nominal or real basis, a survey statistic, a margin its quote writes), and so do the compact references;
assumptions are rendered like the other texts (econ_fidelity).

0.4 (2026-10-28, docs/news-econ-form-subject-2026-10-28.md (private; not in the public repository)): what changed
records its subject (``instrument``, now what it changes or describes; an official statistic is a form, not a subject),
the form of its evidence (``form``) and, for a survey, its ``respondents``; a framework note applies only where all
three match (econ_classification), and a survey's net percentage is its own measure (econ-calc-0.3). Checks take the
analysis version a content was saved under (``version``): an earlier explanation is checked, and an earlier refusal
reproduces, as it was then, with the calculation version and the framework of that version
(econ_framework.for_analysis). Readers are told the classification, or that an earlier explanation did not record it.

0.5 (2026-10-29, docs/news-claims-conditions-2026-10-29.md (private; not in the public repository); brief_claims): what
changed may be at the stage ``procedure`` (an investigation, review or proceeding opened, no measure decided;
econ_classification), a conditional stage like a proposal or a forecast. A brief may record claims (who says what, how
and on what condition), and an explanation's bases may cite them as ``claim:kN``. What changed never rests on a question
put to someone (K4), nor on claims that are only conditional, planned or someone's view at the stage of implementation
or observation (K5), and a channel resting on such a claim states its conditions (K6). A figure whose quote is one of
those claims is shown with what the claim is (brief_claims.note), never as an observed outcome. An explanation saved
under 0.4 or 0.3 is checked and read as it was (``version``), with its own stages, and shows nothing new.

0.6 (2026-10-29, docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)): an alternative, a
competing explanation or an offsetting force, is an interpretation like a channel, so it says what supports it: the
story's own sources (``event_evidence``, citing the fact, report or context item that states it) or an inference resting
on assumptions it names (``bounded_inference``; ALTERNATIVE_SUPPORTS). An earlier model version read a limit on
exchanging holdings as a limit on how much they could be used, in an alternative that could name neither a mechanism's
support nor an assumption, although the source says use is not limited. A figure may be a flow over another or an
unstated period (econ-calc-0.4). Whether a cited source states the mechanism claimed and whether an assumption holds
remain an editor's judgement. An explanation saved under 0.5 or earlier keeps its alternatives as they were and is read
as current (econ_classification.READ_AS_CURRENT). Before any 0.6 explanation was saved, its calculations moved to
econ-calc-0.5 (docs/news-flow-lengths-2026-10-29.md (private; not in the public repository)): flows combine only over a
length their kind establishes.

Reader rendering lives in economics_view (moved unchanged, 29 October 2026); ``reader_view``, ``background`` and
``context_statement`` below are its entry points.
"""
import re

from . import brief_claims, econ_calc, econ_classification, econ_context, econ_fidelity, econ_framework, news_texts
from .accounts import AccountsRefused
from .story_briefs import ADVICE, ATTRIBUTED, CAUSAL, HEDGE, SENTENCE

ANALYSIS_VERSION = econ_classification.CURRENT  # econ-explanation-0.6
# The calculation version each analysis version checks figures and calculations under (pinned: never "the current").
# econ-explanation-0.6 uses econ-calc-0.7 (4 November 2026); no explanation was ever saved under 0.6 with econ-calc-0.4,
# 0.5 or 0.6 (the only first stage sent under it, brief-s1-cc6ad4c83b70c59b, was refused before its figures were read;
# no stored record names econ-calc-0.6, checked read-only on 4 November 2026).
ANALYSES = {"econ-explanation-0.3": "econ-calc-0.2", "econ-explanation-0.4": "econ-calc-0.3",
            "econ-explanation-0.5": "econ-calc-0.3", ANALYSIS_VERSION: econ_calc.CALC_VERSION}
CLASSIFIED_CHANGE = {"stage", "instrument", "form", "respondents", "text", "basis"}
CHANGE_FIELDS = {"econ-explanation-0.3": {"stage", "instrument", "text", "basis"},
                 "econ-explanation-0.4": CLASSIFIED_CHANGE, "econ-explanation-0.5": CLASSIFIED_CHANGE,
                 ANALYSIS_VERSION: CLASSIFIED_CHANGE}
CLAIM_VERSIONS = ("econ-explanation-0.5", ANALYSIS_VERSION)  # Analysis versions whose bases may cite claims.
SUPPORTED_ALTERNATIVES = (ANALYSIS_VERSION,)  # Analysis versions whose alternatives say what supports them.
GUARD_VERSION = "econ-guard-0.3"
SUPPORTS = {"framework": "General economic reasoning: a sourced framework note",
            "event_evidence": "Stated in this story's sources",
            "bounded_inference": "An inference resting on stated assumptions and conditions"}
STATUSES = ("explained", "insufficient_evidence")
STAGES = {"proposal": "Proposed, not decided", "decision": "Decided", "implementation": "Being put into effect",
          "observation": "Observed or measured", "forecast": "Expected or planned",
          "procedure": "Procedure opened, no decision on a measure"}  # 0.5
CONDITIONAL_STAGES = ("proposal", "forecast", "procedure")
SCOPES = {"macro": "Across the economy", "micro": "For particular firms, markets or households"}
HORIZONS = {"immediate": "Immediately", "weeks": "Within weeks", "months": "Over months", "quarters": "Over quarters",
            "years": "Over years", "unclear": "Timing unclear"}
AFFECTED = ("households", "workers", "firms", "industry", "institutions", "government", "region")
ALTERNATIVES = {"competing_explanation": "Another explanation", "offsetting_force": "An offsetting force"}
# 0.6: what supports an alternative. It names no framework note (it has no note field); general reasoning that needs
# one is written as a channel, and anything else as an inference on its stated assumptions.
ALTERNATIVE_SUPPORTS = {"event_evidence": SUPPORTS["event_evidence"],
                        "bounded_inference": "An inference resting on stated assumptions"}
WOULD = ("support", "weaken")
FIELDS = ("status", "insufficient_reason", "change", "significance", "main_uncertainty", "figures", "calculations",
          "assumptions", "channels", "second_order", "alternatives", "watch")
LIMITS = {"text": 500, "short": 200, "step": 200, "name": 80, "reason": 300}
COUNTS = {"channels": (1, 4), "steps": (1, 5), "affected": (1, 5), "second_order": (0, 3), "alternatives": (1, 3),
          "watch": (1, 4), "assumptions": (0, 5), "basis": (1, 8), "alt_basis": (0, 8)}
REF_KINDS = ("fact", "report", "figure", "calc", "context", "claim")  # claim: from 0.5, when the brief records claims
CONTEXT_KEYS = ("item_id", "kind", "publisher", "source", "title", "link", "url", "published", "as_of", "attribution",
                "terms", "role", "relevance", "retrieved", "timing", "story_title")
ID = {"assumptions": re.compile(r"a\d{1,2}"), "channels": re.compile(r"m\d{1,2}"),
      "second_order": re.compile(r"s\d{1,2}")}
# econ-guard-0.1's words (lexical: they catch phrasing, not reasoning).
SURPRISE = re.compile(r"\b(surpris\w*|unexpected\w*|than (?:expected|forecast|anticipated)|consensus|"
                      r"(?:beat|beats|missed|misses|exceeded|topped) (?:expectations|forecasts|estimates)|"
                      r"market expectations|analysts? (?:had )?(?:expected|forecast))\b", re.IGNORECASE)
REAL = re.compile(r"\b(real(?! estate)|inflation[- ]adjusted|deflated|in today's (?:money|dollars))\b", re.IGNORECASE)
NOMINAL = re.compile(r"\b(nominal|current[- ]price|in current (?:dollars|euros|money))\b", re.IGNORECASE)
CHANGE_OF = econ_fidelity.CHANGE_OF
HISTORY = re.compile(r"\b(since (?:19|20)\d\d|highest|lowest|record|(?:than|from) (?:a|last|the previous) "
                     r"(?:year|month|quarter)|a year (?:earlier|ago|before)|year[- ]on[- ]year|previous (?:month|"
                     r"quarter|year|release)|prior (?:month|quarter|year|release)|compared with)\b", re.IGNORECASE)
# Not "market share", "the import share" or "stocks of goods" (seen 2026-10-26); "stocks" alone stays flagged, as it
# may mean shares or inventories: write "inventories".
SECURITIES = re.compile(r"\b(?<!market )(?:shares|stocks)\b(?! of)|\b(?:equities|equity prices|bond (?:prices?|"
                        r"yields?)|futures prices?|stock (?:market|prices?)|share prices?|S&P\s*500|Nasdaq|Dow Jones|"
                        r"Stoxx|FTSE|Nikkei)\b", re.IGNORECASE)
MOVES = re.compile(r"\b(rise|rally|rallies|fall|drop|climb|surge|plunge|soar|slump|outperform|underperform|gain|"
                   r"decline|tumble|jump)\w*\b", re.IGNORECASE)
IMPORT_WORDS = re.compile(r"\b(import\w*|dut(?:y|ies)|customs|tariff schedule|section \d{3}|safeguard\w*)\b",
                          re.IGNORECASE)
CAPITALIZED = re.compile(r"\b[A-Z][\w&'.-]*")
# Certainty in an interpretation; not a financial guarantee ("guaranteed loans", "loan guarantees"), seen 2026-10-26.
CERTAIN = re.compile(r"\b(certainly|definitely|inevitabl[ey]|undoubtedly|surely|(?:is|are|was|were|will be) "
                     r"guaranteed to|guarantees? that)\b", re.IGNORECASE)


def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_brief", detail)


def _text(value: object, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _refuse(f"{label} is text of 1 to {limit} characters.")
    return " ".join(value.split())


def _list(value: object, low: int, high: int, label: str) -> list:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _refuse(f"{label} holds {low} to {high} items.")
    return value


def _shape(value: object, fields: set, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise _refuse(f"{label} has exactly: {', '.join(sorted(fields))}.")
    return value


# ---------------------------------------------------------------- evidence

def evidence(prepared: dict, texts_folder=None, bundle: dict | None = None, released_at: str | None = None) -> dict:
    """What an explanation may rest on: each material report's headline, excerpt and retained text, and the items of
    the context bundle it is prepared with. Reads only."""
    sources = {}
    for row in prepared["reports"]:
        text = row.get("text")
        held = news_texts.text_of(texts_folder, {"entry_id": row["entry_id"], "text_sha256": text["text_sha256"]}) \
            if text and texts_folder is not None else None
        words = "\n".join(part for part in (row["title"], row["excerpt"], held) if part)
        sources[f"report:{row['entry_id']}"] = {"text": words, "publisher": row["publisher"],
                                                "published": row["published_utc"] or row["published"],
                                                "kind": "report", "as_of": None}
    sources.update(econ_context.evidence(bundle))
    everything = "\n".join(row["text"] for row in sources.values())
    return {"sources": sources, "bundle": bundle, "released_at": released_at, "text": everything,
            "numbers": {round(number, 9) for number, _ in econ_calc.numbers(everything)},
            "used": {row["entry_id"] for row in prepared["reports"]}}


def analysis_record(found: dict, version: str = ANALYSIS_VERSION) -> dict:
    """What a brief version records of how its explanation was prepared: under ``version``, the analysis version it
    was checked under (an unchanged revalidation keeps the one it recorded), with that version's calculations and
    framework."""
    framework = econ_framework.for_analysis(version)
    return {"analysis_version": version, "calc_version": ANALYSES[version], "guard_version": GUARD_VERSION,
            "framework_version": framework["framework_version"], "framework_sha256": framework["framework_sha256"],
            "context": econ_context.summary(found["bundle"])}


# ---------------------------------------------------------------- the shape and its references

def _basis(value: object, known: dict, label: str, low: int = 1) -> list[str]:
    rows = _list(value, low, COUNTS["basis"][1], f"{label}'s basis")
    refs = []
    for ref in rows:
        kind, _, name = ref.partition(":") if isinstance(ref, str) else ("", "", "")
        if kind not in REF_KINDS or name not in known[kind]:
            raise _refuse(f"{label} cites {ref!r}, which this explanation's evidence does not hold (fact:N, "
                          "report:<entry ID>, figure:fN, calc:cN, context:<item ID> or a claim the brief records, "
                          "claim:kN).")
        if ref not in refs:
            refs.append(ref)
    return refs


def _assumed(value: object, assumptions: set, label: str) -> list[str]:
    if not isinstance(value, list) or any(name not in assumptions for name in value):
        raise _refuse(f"{label} names only this explanation's assumptions (a1, a2, …).")
    return list(dict.fromkeys(value))


def _ids(rows: list, kind: str) -> set:
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row.get("id"), str) or not ID[kind].fullmatch(row["id"]) or row["id"] in seen:
            raise _refuse(f"Each of {kind} has its own ID ({ID[kind].pattern[0]}1, {ID[kind].pattern[0]}2, …); item "
                          f"{index} does not.")
        seen.add(row["id"])
    return seen


def _empty(economics: dict) -> None:
    for field in ("figures", "calculations", "assumptions", "channels", "second_order", "alternatives", "watch"):
        if economics[field] != []:
            raise _refuse(f"An explanation of insufficient evidence holds no {field}.")
    for field in ("change", "significance", "main_uncertainty"):
        if economics[field] is not None:
            raise _refuse(f"An explanation of insufficient evidence has no {field}.")


def foundations(raw: dict, facts: list[dict], found: dict, version: str = ANALYSIS_VERSION,
                claims: list[dict] | None = None) -> dict:
    """What an explanation rests on, checked exactly as ``checked`` checks it: its figures (each quoted from the
    evidence, with its direction), its calculations (computed here), the references they make known, and what changed
    (its stage and classification, text and basis, resting on a reported fact or report, and naming only figures and
    calculations it holds). ``raw`` holds change, figures and calculations in the explanation's shape. Also the first
    stage of a two-stage model draft (brief_stages), before anything more is prepared from it. ``version``: the analysis
    version it is checked under (an earlier one as it was then). ``claims``: the brief's checked claims (from 0.5),
    which a basis may cite; what changed never rests on a question (K4), nor only on conditional, planned or viewed
    claims when it is implemented or observed (K5)."""
    calc = ANALYSES[version]
    figures = econ_calc.checked_figures(raw["figures"], found["sources"], calc)
    by_id = {row["id"]: row for row in figures}
    calculations = econ_calc.computed(raw["calculations"], by_id, calc)
    if claims is not None and version not in CLAIM_VERSIONS:
        raise _refuse(f"Claims are cited from {CLAIM_VERSIONS[0]}; an explanation under {version} records none.")
    known = {"fact": {str(number) for number in range(1, len(facts) + 1)}, "report": found["used"],
             "figure": set(by_id), "calc": {row["id"] for row in calculations},
             "context": {row["item_id"] for row in (found["bundle"] or {}).get("items", [])},
             "claim": {row["id"] for row in claims or []}}
    change = _shape(raw["change"], CHANGE_FIELDS[version], "change")
    stages = econ_classification.STAGES_OF[version]
    if version not in econ_classification.CLASSIFIED_VERSIONS:
        if change["stage"] not in stages or change["instrument"] not in econ_framework.INSTRUMENTS:
            raise _refuse(f"change names its stage ({', '.join(stages)}) and instrument "
                          f"({', '.join(econ_framework.INSTRUMENTS)}).")
        classified = {"instrument": change["instrument"]}
    else:
        if change["stage"] not in stages:
            raise _refuse(f"change names its stage ({', '.join(stages)}).")
        classified = econ_classification.checked(change, version)
    change_basis = _basis(change["basis"], known, "change")
    if not any(ref.split(":")[0] in ("fact", "report") for ref in change_basis):
        raise _refuse("What changed rests on a reported fact or report.")
    # A fact carries its recorded claims: an indirect citation must not hide an interviewer's question either.
    if any(row["modality"] == "question" for row in brief_claims.cited(change_basis, claims, facts)):
        raise _refuse("What changed never rests on a question or premise put to someone: it is not their statement, "
                      "nor a development (K4).")
    if brief_claims.unrealised_only(change_basis, claims, facts) and \
            change["stage"] in ("implementation", "observation"):
        raise _refuse(f"What changed rests only on claims that are conditional, planned or someone's view, so it is "
                      f"not {STAGES[change['stage']].lower()} (K5).")
    text = _text(change["text"], LIMITS["text"], "What changed")
    unknown = [name for name in econ_calc.placeholders(text) if name not in by_id and name not in known["calc"]]
    if unknown:
        raise _refuse(f"A text names figures or calculations this explanation does not hold: {', '.join(unknown)}.")
    return {"figures": figures, "by_id": by_id, "calculations": calculations, "known": known,
            "change": {"stage": change["stage"], **classified, "text": text, "basis": change_basis}}


def checked(economics: object, facts: list[dict], found: dict, version: str = ANALYSIS_VERSION,
            claims: list[dict] | None = None) -> dict:
    """The explanation in its exact shape, every reference resolved and every derived figure computed; refused
    otherwise. ``facts`` are the brief's checked facts; ``found`` is ``evidence(...)``; ``version`` the analysis
    version it is checked under, with that version's calculations and framework (an earlier one as it was then);
    ``claims`` the brief's checked claims (from 0.5)."""
    if version not in ANALYSES:
        raise _refuse(f"An explanation is checked under a known analysis version ({', '.join(ANALYSES)}).")
    economics = _shape(economics, set(FIELDS), "An economic explanation")
    framework = econ_framework.for_analysis(version)
    notes = framework["notes"]
    if economics["status"] not in STATUSES:
        raise _refuse(f"An explanation's status is {' or '.join(STATUSES)}.")
    if economics["status"] == "insufficient_evidence":
        _empty(economics)
        return {"analysis_version": version, "status": "insufficient_evidence",
                "insufficient_reason": _text(economics["insufficient_reason"], LIMITS["reason"], "The reason"),
                **{field: None for field in ("change", "significance", "main_uncertainty")},
                **{field: [] for field in FIELDS[5:]}, "context": [], "framework": None}
    if economics["insufficient_reason"] is not None:
        raise _refuse("An explained story gives no insufficient_reason.")
    base = foundations(economics, facts, found, version, claims)
    figures, by_id, calculations, known = base["figures"], base["by_id"], base["calculations"], base["known"]
    assumptions = []
    for row in _list(economics["assumptions"], *COUNTS["assumptions"], "assumptions"):
        _shape(row, {"id", "text"}, "An assumption")
        assumptions.append({"id": row["id"], "text": _text(row["text"], LIMITS["short"], "An assumption")})
    names = _ids(assumptions, "assumptions")
    change, change_basis = base["change"], base["change"]["basis"]
    conditional = change["stage"] in CONDITIONAL_STAGES
    significance = _shape(economics["significance"], {"text", "basis"}, "significance")
    channels = []
    for index, row in enumerate(_list(economics["channels"], *COUNTS["channels"], "channels"), start=1):
        where = f"Channel {index}"
        _shape(row, {"id", "scope", "support", "note", "text", "steps", "affected", "conditions", "horizon", "basis",
                     "assumptions"}, where)
        if row["scope"] not in SCOPES or row["horizon"] not in HORIZONS or row["support"] not in SUPPORTS:
            raise _refuse(f"{where} names its scope ({', '.join(SCOPES)}), horizon ({', '.join(HORIZONS)}) and what "
                          f"supports it ({', '.join(SUPPORTS)}).")
        if row["support"] == "framework" and row["note"] is None:
            raise _refuse(f"{where}: a channel supported by a framework names the note.")
        if row["note"] is not None:
            note = notes.get(row["note"])
            if note is None:
                raise _refuse(f"{where} names a framework note that does not exist ({row['note']}).")
            reason = econ_classification.mismatch(note, change, version)
            if reason:
                raise _refuse(f"{where}: the mechanism “{note['title']}” {reason}.")
        affected = []
        for party in _list(row["affected"], *COUNTS["affected"], f"{where}'s affected"):
            _shape(party, {"kind", "name", "how"}, f"{where}'s affected party")
            if party["kind"] not in AFFECTED:
                raise _refuse(f"{where}'s affected parties are {', '.join(AFFECTED)}.")
            affected.append({"kind": party["kind"], "name": _text(party["name"], LIMITS["name"], f"{where}'s name"),
                             "how": _text(party["how"], LIMITS["short"], f"{where}'s how")})
        conditions = None if row["conditions"] is None else _text(row["conditions"], LIMITS["short"],
                                                                     f"{where}'s conditions")
        if conditional and conditions is None:
            raise _refuse(f"{where}: for a {change['stage']}, a channel states the condition under which it would "
                          "follow.")
        if conditions is None and any(claim["modality"] in brief_claims.NON_ASSERTED
                                      for claim in brief_claims.cited(row["basis"] or [], claims, facts)):
            raise _refuse(f"{where} rests on a claim that is not stated as so (conditional, planned, a view or a "
                          "question), so it states the conditions under which it would follow (K6).")
        if row["support"] == "bounded_inference" and (conditions is None or not row["assumptions"]):
            raise _refuse(f"{where}: an inference states the assumptions and the conditions that bound it.")
        if row["support"] == "event_evidence" and not any(str(ref).split(":")[0] in ("fact", "report", "context")
                                                          for ref in row["basis"] or []):
            raise _refuse(f"{where}: a mechanism stated in the sources cites the fact, report or context item that "
                          "states it.")
        channels.append({"id": row["id"], "scope": row["scope"], "support": row["support"], "note": row["note"],
                         "text": _text(row["text"], LIMITS["text"], f"{where}'s text"),
                         "steps": [_text(step, LIMITS["step"], f"{where}'s step") for step in
                                   _list(row["steps"], *COUNTS["steps"], f"{where}'s steps")],
                         "affected": affected, "conditions": conditions, "horizon": row["horizon"],
                         "basis": _basis(row["basis"], known, where),
                         "assumptions": _assumed(row["assumptions"], names, where)})
    channel_ids = _ids(channels, "channels")
    effects = []
    for index, row in enumerate(_list(economics["second_order"], *COUNTS["second_order"], "second_order"), start=1):
        where = f"Second-order effect {index}"
        _shape(row, {"id", "from", "text", "conditions", "horizon", "basis", "assumptions"}, where)
        if row["from"] not in channel_ids:
            raise _refuse(f"{where} follows from one of this explanation's channels (m1, m2, …).")
        if row["horizon"] not in HORIZONS:
            raise _refuse(f"{where}'s horizon is one of {', '.join(HORIZONS)}.")
        effects.append({"id": row["id"], "from": row["from"],
                        "text": _text(row["text"], LIMITS["text"], f"{where}'s text"),
                        "conditions": _text(row["conditions"], LIMITS["short"], f"{where}'s conditions"),
                        "horizon": row["horizon"], "basis": _basis(row["basis"], known, where),
                        "assumptions": _assumed(row["assumptions"], names, where)})
    _ids(effects, "second_order")
    alternatives = []
    supported = version in SUPPORTED_ALTERNATIVES
    for index, row in enumerate(_list(economics["alternatives"], *COUNTS["alternatives"], "alternatives"), start=1):
        where = f"Alternative {index}"
        _shape(row, {"kind", "support", "text", "basis", "assumptions"} if supported else {"kind", "text", "basis"},
               where)
        if row["kind"] not in ALTERNATIVES:
            raise _refuse(f"An alternative is a {' or an '.join(ALTERNATIVES)}.")
        text = _text(row["text"], LIMITS["text"], where)
        basis = _basis(row["basis"], known, where, COUNTS["alt_basis"][0])
        if not supported:
            alternatives.append({"kind": row["kind"], "text": text, "basis": basis})
            continue
        if row["support"] not in ALTERNATIVE_SUPPORTS:
            raise _refuse(f"{where} says what supports it ({', '.join(ALTERNATIVE_SUPPORTS)}).")
        assumed = _assumed(row["assumptions"], names, where)
        if row["support"] == "bounded_inference" and not assumed:
            raise _refuse(f"{where}: an inference states the assumptions it rests on.")
        if row["support"] == "event_evidence" and not any(ref.split(":")[0] in ("fact", "report", "context")
                                                          for ref in basis):
            raise _refuse(f"{where}: what the sources state cites the fact, report or context item that states it.")
        alternatives.append({"kind": row["kind"], "support": row["support"], "text": text, "basis": basis,
                             "assumptions": assumed})
    watch = []
    for index, row in enumerate(_list(economics["watch"], *COUNTS["watch"], "watch"), start=1):
        _shape(row, {"observable", "would", "text"}, f"What to watch {index}")
        if row["would"] not in WOULD:
            raise _refuse("What to watch says whether it would support or weaken the reading.")
        watch.append({"observable": _text(row["observable"], LIMITS["name"], f"What to watch {index}"),
                      "would": row["would"], "text": _text(row["text"], LIMITS["short"], f"What to watch {index}")})
    result = {"analysis_version": version, "status": "explained", "insufficient_reason": None,
              "change": change,
              "significance": {"text": _text(significance["text"], LIMITS["text"], "Why it matters"),
                               "basis": _basis(significance["basis"], known, "Why it matters")},
              "main_uncertainty": _text(economics["main_uncertainty"], LIMITS["short"], "The main uncertainty"),
              "figures": figures, "calculations": calculations, "assumptions": assumptions, "channels": channels,
              "second_order": effects, "alternatives": alternatives, "watch": watch}
    unknown = [name for _, text in statements(result) for name in econ_calc.placeholders(text)
               if name not in by_id and name not in known["calc"]]
    if unknown:
        raise _refuse(f"A text names figures or calculations this explanation does not hold: {', '.join(unknown)}.")
    cited = {ref.partition(":")[2] for ref in _all_refs(result) if ref.startswith("context:")}
    cited |= {row["source"].partition(":")[2] for row in figures if row["source"].startswith("context:")}
    result["context"] = [{key: row.get(key) for key in CONTEXT_KEYS}
                         for row in (found["bundle"] or {}).get("items", []) if row["item_id"] in cited]
    result["framework"] = econ_framework.snapshot([row["note"] for row in channels if row["note"]], framework)
    return result


def _all_refs(economics: dict) -> list[str]:
    rows = economics["change"]["basis"] + economics["significance"]["basis"]
    for field in ("channels", "second_order", "alternatives"):
        rows += [ref for row in economics[field] for ref in row["basis"]]
    return rows


# ---------------------------------------------------------------- econ-guard-0.1

def statements(economics: dict) -> list[tuple[str, str]]:
    """Every text of an explanation, with where it is."""
    if economics["status"] != "explained":
        return [("insufficient_reason", economics["insufficient_reason"])]
    rows = [("change", economics["change"]["text"]), ("significance", economics["significance"]["text"]),
            ("main_uncertainty", economics["main_uncertainty"])]
    rows += [(f"assumptions[{index}]", row["text"]) for index, row in enumerate(economics["assumptions"])]
    for index, row in enumerate(economics["channels"]):
        rows += [(f"channels[{index}]", row["text"])]
        rows += [(f"channels[{index}].steps[{step}]", text) for step, text in enumerate(row["steps"])]
        rows += [(f"channels[{index}].affected[{n}]", f"{party['name']}: {party['how']}")
                 for n, party in enumerate(row["affected"])]
        rows += [(f"channels[{index}].conditions", row["conditions"])] if row["conditions"] else []
    for index, row in enumerate(economics["second_order"]):
        rows += [(f"second_order[{index}]", row["text"]), (f"second_order[{index}].conditions", row["conditions"])]
    rows += [(f"alternatives[{index}]", row["text"]) for index, row in enumerate(economics["alternatives"])]
    rows += [(f"watch[{index}]", f"{row['observable']}: {row['text']}") for index, row in
             enumerate(economics["watch"])]
    return rows


def _cited(economics: dict, where: str) -> list[str]:
    """The basis of the statement at ``where`` (empty for a text that has none)."""
    head, _, rest = where.partition("[")
    if head in ("change", "significance"):
        return economics[head]["basis"]
    if head in ("channels", "second_order", "alternatives") and "." not in where:
        return economics[head][int(rest.split("]")[0])]["basis"]
    return []


def _benchmarked(found: dict, refs: list[str]) -> bool:
    """Whether a cited context item is an expectations benchmark dated before the release."""
    released = (found.get("released_at") or "")[:10]
    for ref in refs:
        source = found["sources"].get(ref) if ref.startswith("context:") else None
        if source and source["kind"] == "expectation" and source["as_of"] and released and source["as_of"] < released:
            return True
    return False


def _later(economics: dict, found: dict) -> set[str]:
    """References to context published after the story was first reported, and the figures and calculations that
    rest on it."""
    later = {ref for ref, source in found["sources"].items() if source.get("timing") == "after"}
    figures = {row["id"] for row in economics["figures"] if row["source"] in later}
    calcs = {row["id"] for row in economics["calculations"] if set(row["inputs"]) & figures}
    return later | {f"figure:{name}" for name in figures} | {f"calc:{name}" for name in calcs}


def findings(economics: dict, found: dict) -> list[dict]:
    """econ-guard-0.1: what stops publication, each with where it was found. Words and numbers, not economics."""
    rows = []

    def flag(where: str, rule: str, matched: str, detail: str) -> None:
        rows.append({"where": f"economics.{where}", "rule": rule, "matched": matched, "detail": detail})

    if economics["status"] != "explained":
        return rows
    values = {row["id"]: row for row in economics["figures"] + economics["calculations"]}
    for where, text in statements(economics):
        bare = econ_calc.PLACEHOLDER.sub(" ", text)
        found_advice = ADVICE.search(text)
        if found_advice:
            flag(where, "advice", found_advice.group(0), "An explanation never advises anyone to trade.")
        for number, _ in econ_calc.numbers(bare):
            if round(number, 9) not in found["numbers"]:
                flag(where, "unsourced_number", f"{number:g}", "A number is shown only as a quoted figure or a "
                     "calculation, or as the evidence states it; this one is not in the evidence.")
                break
        for sentence in SENTENCE.findall(text):
            cause = CAUSAL.search(sentence)
            if cause and not ATTRIBUTED.search(sentence):
                flag(where, "causal_claim", cause.group(0), "A cause may be reported as someone's statement, never "
                                                            "claimed by the explanation itself.")
            if SECURITIES.search(sentence) and MOVES.search(sentence):
                flag(where, "price_forecast", SECURITIES.search(sentence).group(0), "An explanation does not forecast "
                                                                                    "security prices.")
            certain = CERTAIN.search(sentence)
            if certain:
                flag(where, "certainty", certain.group(0), "An interpretation is a possibility, never a certainty.")
            names = econ_calc.placeholders(sentence)
            bases = {values[name]["basis"] for name in names if name in values}
            if REAL.search(sentence) and "nominal" in bases:
                flag(where, "real_nominal", REAL.search(sentence).group(0), "A nominal figure is not a real one; "
                     "deflate it by a price change of the same period (a calculation).")
            if NOMINAL.search(sentence) and "real" in bases:
                flag(where, "real_nominal", NOMINAL.search(sentence).group(0), "A real figure is called nominal.")
        for match in CHANGE_OF.finditer(text):
            name = match.group(1) or match.group(2)
            if name in values and values[name].get("measure") == "level":
                flag(where, "level_as_change", match.group(0), "A level is not a change: compute the change from two "
                                                               "levels, or quote the change itself.")
        surprise = SURPRISE.search(text)
        if surprise and not _benchmarked(found, _cited(economics, where)):
            flag(where, "unsupported_expectation", surprise.group(0), "A release is a surprise only against a "
                 "contemporaneous expectations benchmark in the context bundle, cited here.")
        history = HISTORY.search(bare)
        if history and not any(ref.split(":")[0] in ("figure", "calc", "context", "fact")
                               for ref in _cited(economics, where)):
            flag(where, "historical_comparison", history.group(0), "A comparison with the past rests on cited "
                                                                   "evidence: a fact, a figure or a context item.")
    for index, row in enumerate(economics["channels"]):
        if not HEDGE.search(row["text"]):
            flag(f"channels[{index}]", "unhedged", "", "A channel says how the development may work (may, might, "
                                                       "could, would, if, …).")
        for party in row["affected"]:
            if party["kind"] == "firms" and not _named_in(party["name"], found["text"]):
                flag(f"channels[{index}].affected", "company_not_in_evidence", party["name"], "A named company is one "
                     "the evidence names; otherwise describe the kind of firm.")
    for index, row in enumerate(economics["second_order"]):
        if not HEDGE.search(row["text"]):
            flag(f"second_order[{index}]", "unhedged", "", "A second-order effect is a possibility (may, might, …).")
    for row in economics["figures"]:
        check = row.get("direction_check")
        if check == "contradicted":
            flag(f"figures[{row['id']}]", "sign_contradicted", row["quote"][:60], "The quote states this change as a "
                 "decline, but the figure is positive: give it the sign the words state (sign from_words).")
        elif check == "unclear":
            flag(f"figures[{row['id']}]", "sign_unclear", row["sign_words"] or "", "The cited words do not establish "
                 "the figure's direction; an editor must confirm it before publication.")
    later = _later(economics, found)
    cited = set(economics["change"]["basis"]) | {
        f"{'calc' if name.startswith('c') else 'figure'}:{name}" for name in econ_calc.placeholders(
            economics["change"]["text"])}
    if cited & later:
        flag("change", "retrospective_as_event", ", ".join(sorted(cited & later)), "What happened rests on what was "
             "known when the story was reported; context published after it is later context, to be cited elsewhere "
             "and shown as such.")
    if economics["change"]["instrument"] == "import_tariff" and not IMPORT_WORDS.search(found["text"]):
        flag("change", "instrument_unsupported", "import_tariff", "Reading this as a tariff on imports needs evidence "
             "that speaks of imports or duties; a charge for a domestic service is not an import tariff.")
    return rows


def _named_in(name: str, text: str) -> bool:
    """Whether every capitalised word of a firm's name appears in the evidence (or its stem: "Iranian" in "Iran")."""
    words = text.casefold()
    for token in CAPITALIZED.findall(name):
        token = token.casefold().rstrip(".").removesuffix("'s")
        stems = {token, token[:-3] if token.endswith("ian") else token, token[:-1] if token.endswith("s") else token,
                 token[:-2] if token.endswith("an") else token}
        if not any(len(stem) >= 2 and stem in words for stem in stems):
            return False
    return True


# ---------------------------------------------------------------- what readers see (economics_view)

def reader_view(economics: dict | None, facts: list[dict], recorded: dict | None = None,
                claims: list[dict] | None = None) -> dict | None:
    """The explanation as readers see it (economics_view.reader_view, moved there unchanged)."""
    from . import economics_view
    return economics_view.reader_view(economics, facts, recorded, claims)


def background(economics: dict, recorded: dict | None) -> dict:
    """The framework notes an explanation was prepared with (economics_view.background)."""
    from . import economics_view
    return economics_view.background(economics, recorded)


def context_statement(economics: dict | None) -> str | None:
    """What the explanation read beyond the story's own material (economics_view.context_statement)."""
    from . import economics_view
    return economics_view.context_statement(economics)

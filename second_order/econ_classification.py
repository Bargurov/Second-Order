"""What changed, classified by its subject and by the form of its evidence (econ-explanation-0.4).

Up to econ-explanation-0.3 a development had one ``instrument``, which mixed how its evidence was produced (an official
statistic) with what it describes (credit conditions, prices). A bank lending survey classified as an official
statistic was refused the credit notes; classified by subject it would have been offered a note about firms' answers
(docs/news-econ-form-subject-2026-10-28.md (private; not in the public repository)). From 0.4 what changed records,
apart:

- ``instrument``: its subject, what it changes or describes (econ_framework.SUBJECTS); an official statistic is a form;
- ``form``: how its evidence was produced (econ_framework.FORMS): a reported observation, respondents' answers in a
  survey, a forecast or scenario, an announced or adopted decision (a proposal or measure included), a statement of
  views, or ``unclear`` when the material does not say, which keeps the uncertainty and admits no framework note;
- ``respondents``: whose answers a survey reports (banks, firms, households, other, not stated), and nothing otherwise.

A form takes only the stages it can have (FORM_STAGES): a survey's answers are observed answers, never a decision or a
forecast, however they look ahead; a forecast is never a realised outcome. A framework note applies only where its
subjects, forms and respondents all match (``mismatch``), so a subject match never admits a note that assumes other
evidence or other respondents, and a central bank's survey is never read through its policy's mechanism.

Earlier explanations read under the contract they recorded (``mismatch`` with an earlier analysis version applies the
rule they were checked under). ``reassessment`` is the explicit, deterministic compatibility rule for an explanation
saved under econ-explanation-0.3: it is current unless a rule of 0.4 can be shown, from what it recorded, to affect it.
What it never recorded (its form and respondents) is shown as not recorded, not inferred.

econ-explanation-0.5 (docs/news-claims-conditions-2026-10-29.md (private; not in the public repository)) adds one stage,
``procedure``: an investigation, review or proceeding has been formally opened and no measure has been decided. Four
published stories of that one kind of event carried three labels ("Being put into effect", "Proposed, not decided",
"Decided"), each saying something false of it, and the stage table accepted all of them. A procedure is never a survey's
answers or a forecast; one announced for later ("to be initiated soon") is a forecast, and its outcome a decision or its
implementation. Each analysis version keeps its own stage table (FORM_STAGES_OF): an explanation saved under 0.4 is
checked, and an earlier refusal reproduces, with the stages it had. Nothing 0.4 recorded can show that a rule of 0.5
affects it (0.5 adds a stage and claim references, which no 0.4 explanation holds), so it is read as current
(READ_AS_CURRENT) and never relabelled.

econ-explanation-0.6 (docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)) keeps 0.5's
stages and classification; it changes what an alternative records (story_economics). An explanation saved under 0.5 is
read as current, like one of 0.4. """
from . import econ_framework as ef
from .accounts import AccountsRefused

CLASSIFIED = "econ-explanation-0.4"  # The first analysis version that records form and respondents.
PROCEDURAL = "econ-explanation-0.5"  # 0.5: the procedural stage and claim references.
CURRENT = "econ-explanation-0.6"  # 0.6: an alternative's support and assumptions (story_economics); stages as 0.5.
CLASSIFIED_VERSIONS = (CLASSIFIED, PROCEDURAL, CURRENT)  # The analysis versions that record form and respondents.
STAGES_04 = ("proposal", "decision", "implementation", "observation", "forecast")
STAGES = (*STAGES_04, "procedure")
FORM_STAGES_04 = {"reported_observation": ("observation", "implementation"),
                  "survey_answers": ("observation",),
                  "forecast_or_scenario": ("forecast",),
                  "announcement_or_decision": ("proposal", "decision", "implementation", "forecast"),
                  "statement": ("proposal", "observation", "forecast"),
                  "unclear": STAGES_04}
# An opened procedure is reported, announced or stated; never a survey's answers or a forecast.
FORM_STAGES = {form: (*stages, "procedure") if form in ("reported_observation", "announcement_or_decision",
                                                          "statement") else stages
               for form, stages in FORM_STAGES_04.items()} | {"unclear": STAGES}
FORM_STAGES_OF = {CLASSIFIED: FORM_STAGES_04, PROCEDURAL: FORM_STAGES, CURRENT: FORM_STAGES}
STAGES_OF = {"econ-explanation-0.3": STAGES_04, CLASSIFIED: STAGES_04, PROCEDURAL: STAGES, CURRENT: STAGES}
LEGACY_NOTE = ("Classified as “{label}” before the form of evidence was recorded apart from its subject: its evidence "
               "form and any survey respondents were not recorded.")


def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_brief", detail)


def _labels(names, table: dict) -> str:
    return ", ".join(table.get(name, "any subject" if name == ef.ANY else name) for name in names)


def checked(change: dict, version: str = CURRENT) -> dict:
    """The classification of what changed under ``version`` (0.4 or later): its stage, subject, form and respondents,
    consistent with each other under that version's stage table; refused otherwise. Nothing is filled in."""
    if change["instrument"] == "official_statistic":
        raise _refuse("An official statistic is a form of evidence, not a subject: give what it measures as the "
                      "subject (or other) and its form (reported_observation or survey_answers).")
    if change["instrument"] not in ef.SUBJECTS:
        raise _refuse(f"What changed names its subject ({', '.join(ef.SUBJECTS)}).")
    if change["form"] not in ef.FORMS:
        raise _refuse(f"What changed names the form of its evidence ({', '.join(ef.FORMS)}).")
    if change["form"] == "survey_answers" and change["respondents"] not in ef.RESPONDENTS:
        raise _refuse(f"A survey names whose answers it reports (respondents: {', '.join(ef.RESPONDENTS)}).")
    if change["form"] != "survey_answers" and change["respondents"] is not None:
        raise _refuse("Only a survey has respondents; for any other form of evidence respondents is null.")
    allowed = FORM_STAGES_OF[version][change["form"]]
    if change["stage"] not in allowed:
        raise _refuse(f"What changed is {ef.FORMS[change['form']]}, so its stage is {' or '.join(allowed)}, not "
                      f"{change['stage']}.")
    return {"instrument": change["instrument"], "form": change["form"], "respondents": change["respondents"]}


def mismatch(note: dict, change: dict, version: str = CURRENT) -> str | None:
    """Why a framework note does not apply to what changed, in words (None when it applies): from 0.4 its subjects,
    forms and respondents must all match; under an earlier version, as it was then, its instruments."""
    if version not in CLASSIFIED_VERSIONS:
        if change["instrument"] in note["applies_to"]:
            return None
        return (f"applies to {_labels(note['applies_to'], ef.INSTRUMENTS)}, not to "
                f"{ef.INSTRUMENTS[change['instrument']]}")
    if ef.ANY not in note["applies_to"] and change["instrument"] not in note["applies_to"]:
        return f"applies to {_labels(note['applies_to'], ef.SUBJECTS)}, not to {ef.SUBJECTS[change['instrument']]}"
    if change["form"] not in note["forms"]:
        return f"rests on {_labels(note['forms'], ef.FORMS)}, not on {ef.FORMS[change['form']]}"
    if change["form"] == "survey_answers" and change["respondents"] not in note["respondents"]:
        return (f"describes the answers of {_labels(note['respondents'], ef.RESPONDENTS)}, not of "
                f"{ef.RESPONDENTS.get(change['respondents'], change['respondents'])}")
    return None


def applicable(notes: dict, change: dict) -> list[dict]:
    """The notes that apply to what changed (0.4 and later), in the framework's order."""
    return [note for note in notes.values() if mismatch(note, change) is None]


def describe(change: dict) -> str:
    """What changed's classification in the words a request uses (stage, subject, form and respondents)."""
    if "form" not in change:
        return f"stage {change['stage']}; instrument {change['instrument']}"
    form = change["form"] + (f" of {change['respondents']}" if change["respondents"] else "")
    return f"stage {change['stage']}; subject {change['instrument']}; evidence {form}"


def labels(change: dict) -> dict:
    """What readers are told of the classification: its subject, its form and respondents, or that an earlier
    explanation did not record them."""
    if "form" in change:
        return {"instrument_label": ef.SUBJECTS[change["instrument"]], "form_label": ef.FORMS[change["form"]],
                "respondents_label": ef.RESPONDENTS[change["respondents"]] if change["respondents"] else None,
                "classification_note": None}
    label = ef.INSTRUMENTS[change["instrument"]]
    return {"instrument_label": label, "form_label": None, "respondents_label": None,
            "classification_note": LEGACY_NOTE.format(label=label)}


# ---------------------------------------------------------------- earlier explanations (news-explanations-0.4)

# Earlier versions read as current: 0.3 unless its reassessment shows a 0.4 rule affects it; 0.4 always (no rule of 0.5
# can be shown from what it recorded); 0.5 always, with its econ-calc-0.3 (0.6 adds an alternative's support and a
# flow over another period, neither of which an earlier explanation recorded, so no rule of 0.6 can be shown to
# affect it). econ-calc-0.4 is not read as current: it compared flows whose lengths were not established, which
# econ-calc-0.5 refuses, so a result saved under it is prepared again (none was saved). econ-calc-0.5 is not read as
# current either: it read "350 000" as 350 and 0 (econ-calc-0.6), so a result saved under it would be prepared again
# (none was saved). Nor is econ-calc-0.6: it read "In 2025 350 000" and "350 000-400 000" in fragments and let a figure
# take one end of a range as an exact point (econ-calc-0.7; none was saved). 0.2 and 0.3 stay current: re-checked on
# 1 November 2026 and again on 4 November 2026 (all 220 saved figures, 70 versions, read alike under econ-calc-0.6 and
# 0.7), no figure saved under them reads differently
# (docs/news-space-thousands-2026-11-01.md (private; not in the public repository),
# docs/news-number-boundaries-2026-11-04.md (private; not in the public repository)). Pinned by
# tests/test_econ_consistency.py.
READ_AS_CURRENT = {"analysis": ("econ-explanation-0.3", CLASSIFIED, PROCEDURAL),
                   "calculation": ("econ-calc-0.2", "econ-calc-0.3")}
LEGACY_SUBJECT = {name: (None if name == "official_statistic" else name) for name in ef.INSTRUMENTS}


def reassessment(economics: dict, notes: dict) -> list[str]:
    """Why an explanation saved under econ-explanation-0.3 needs reassessing under 0.4, from what it recorded only
    (empty when no rule of 0.4 can be shown to affect it). ``notes``: the framework notes it used, as recorded.

    - A figure recorded as a share outside 0% to 100% is no share (econ-calc-0.3): a survey's net balance read as one.
    - A note it used must still apply to its recorded subject (LEGACY_SUBJECT: an official statistic recorded no
      subject, so only a note about any subject applies) and rest on a form its recorded stage can have.
    Its form and respondents were never recorded, so they are not checked, and readers are told so (``labels``)."""
    reasons = []
    for row in economics.get("figures") or []:
        if row.get("measure") == "share" and row.get("unit") == "percent" and not 0 <= row["value"] <= 100:
            reasons.append(f"its figure {row['id']} is recorded as a share of {row['value']:g}%, which no share can "
                           "be: under econ-calc-0.3 a survey's balance of answers is a net percentage")
    current = ef.framework()["notes"]
    change = economics.get("change") or {}
    subject = LEGACY_SUBJECT.get(change.get("instrument"))
    for name in dict.fromkeys(row["note"] for row in economics.get("channels") or [] if row["note"]):
        note = current.get(name)
        title = (notes.get(name) or {}).get("title", name)
        if note is None:
            continue  # A removed note is reported by econ_framework.changed.
        if ef.ANY not in note["applies_to"] and subject not in note["applies_to"]:
            what = (f"and this version recorded only “{ef.INSTRUMENTS[change['instrument']]}”, which names no subject"
                    if subject is None else f"not to {ef.SUBJECTS[subject]}")
            reasons.append(f"the framework note “{title}” it uses now applies to "
                           f"{_labels(note['applies_to'], ef.SUBJECTS)}, {what}")
        elif not any(change.get("stage") in FORM_STAGES_04[form] for form in note["forms"]):
            reasons.append(f"the framework note “{title}” it uses now rests on {_labels(note['forms'], ef.FORMS)}, "
                           f"which a development at stage {change.get('stage')} cannot be")
    return reasons

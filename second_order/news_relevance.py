"""Economic relevance of a news story (news-relevance-0.1): an annotation of what the story's permitted material reports,
checked against that material, and deterministic, versioned decisions over it.

The annotation (ANNOTATION_VERSION, ``Annotation``) is prepared by the AI model in this application or by an AI
assistant outside it (relevance_requests, relevance_batches), from the story's permitted material only, under the
editorial scope SCOPE_VERSION. It says what kind of item the story is (a reported development, product coverage,
consumer advice, opinion, a ceremonial message, promotion or a digest); for a development, its type and the substantive
change; which businesses, industries, institutions, governments, populations, markets or regions it affects; which
economic dimensions the material supports (DIMENSIONS) and how; its evidenced scope (a reach, and the magnitudes the
material states); what is ambiguous or missing; and a provisional verdict (relevant, outside the editorial scope, or
insufficient information) with an explanation. Every claim that names evidence names a report of the material and
quotes it. ``check_evidence`` looks for each quote in that report's headline, excerpt or retained publication text
(NFKC, whitespace, typographic quotes and dashes, and case normalised) and records where it was found; a quote that is
not found, or names a report outside the material, supports nothing. An annotation is an editorial judgement made with
a model: it is never presented as measured market impact, and no number it states ranks anything.

Three decisions are kept apart, each deterministic code over saved records:

1. Economic relevance (DECISION_VERSION, ``decide``): ``relevant`` only when the verdict is relevant, the item is a
   reported development, what changed is quoted from the material and at least one economic dimension is supported by a
   quote; ``outside_scope`` when the verdict says so, unless the item is a development whose material supports two or
   more dimensions; ``insufficient`` when the verdict says the material cannot tell; every disagreement between the
   verdict and the annotation's own structure is ``needs_review``, for an editor. An editor's recorded judgement, with
   its reason, decides instead of any annotation (``relevance_of``). A story with no report whose publisher allows its
   use by a model is ``restricted``: it is never sent to a model, and only an editor can judge it. A failed attempt (a
   provider error, a refusal, a reply that fails the schema) is ``unavailable``, never outside the scope. A story never
   assessed is ``pending``.
2. Editorial importance (IMPORTANCE_VERSION, ``importance``): fixed points from the annotation's categories (the
   development's type, its reach, and whether the material states its size), for relevant stories only.
3. Freshness and continuing-story priority: news_rank, which uses the two above and nothing else from a model.

Reads only read: the decisions are made from the saved annotation and its saved evidence check; nothing here calls a
model or a publisher. ``record`` and ``review`` are the explicit writes.
"""
from datetime import datetime
import json
import unicodedata
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from . import newsroom_store as ns
from .accounts import AccountsRefused
from .news_stories import checked_reason
from .schema import FrozenModel

RELEVANCE_VERSION = "news-relevance-0.1"
ANNOTATION_VERSION = "relevance-annotation-0.1"
SCOPE_VERSION = "economic-scope-0.1"
EVIDENCE_VERSION = "relevance-evidence-0.1"
DECISION_VERSION = "relevance-decision-0.1"
IMPORTANCE_VERSION = "news-importance-0.1"
METHODS = ("model", "assisted", "synthetic")
STATES = ("relevant", "outside_scope", "insufficient", "needs_review", "unavailable", "restricted", "pending")
REVIEW_VERDICTS = ("relevant", "outside_scope", "insufficient_information", "cleared")
VERDICT_STATE = {"relevant": "relevant", "outside_scope": "outside_scope", "insufficient_information": "insufficient"}

REPORT_KINDS = {
    "development": "a reported development: something happened, was decided or changed, or new information was "
                   "published",
    "product_coverage": "product coverage: a launch, showcase, roundup or review of products or apps",
    "consumer_advice": "consumer advice: tips, a how-to or a tutorial",
    "opinion": "opinion: commentary, analysis or argument without a new development",
    "ceremonial": "a ceremonial item: a proclamation, commemoration, greeting, award or message",
    "promotional": "promotion: self-promotion, a recap of earlier claims or achievements, or an event announcement",
    "digest": "a digest of several unrelated items",
    "other": "another kind of item",
}
EVENT_TYPES = {
    "policy_decision": "an enacted or formally adopted policy: a law, order, regulation, tariff, sanction or rate "
                       "decision",
    "policy_proposal": "a proposed policy, consultation, plan or negotiating position not yet adopted",
    "enforcement": "an investigation, ruling, fine, settlement or commitment obtained by an authority",
    "official_data": "new official statistics, survey results or data",
    "official_statement": "a speech, interview, remarks or statement by an official or an institution",
    "agreement": "an agreement or resolution between governments, institutions or parties",
    "corporate_action": "a company's deal, financing, investment, production, pricing, hiring or job cuts",
    "disruption": "a strike, outage, accident, shortage or weather event affecting activity",
    "other_development": "another development",
}
DIMENSIONS = {
    "demand": "what households, firms or governments buy", "revenue": "what businesses earn",
    "costs": "what producing or doing business costs", "prices": "prices as the sources state them",
    "production": "what is produced or supplied", "employment": "jobs, wages and working conditions",
    "financing": "borrowing, lending, investment funding and financial conditions",
    "competition": "how firms compete, market power and entry", "regulation": "rules businesses must follow",
    "trade": "trade across borders: tariffs, quotas, export controls, trade agreements",
    "capacity": "the capacity to produce, transport or store",
}
AFFECTED_KINDS = ("business", "industry", "institution", "government", "population", "market", "region")
REACH = ("global", "international", "national", "regional", "sector", "company", "local", "unclear")
VERDICTS = ("relevant", "outside_scope", "insufficient_information")

Text = Annotated[str, Field(min_length=1, max_length=600)]
Short = Annotated[str, Field(min_length=1, max_length=300)]


class Evidence(FrozenModel):
    report: Annotated[str, Field(min_length=1, max_length=200)]
    quote: Annotated[str, Field(min_length=1, max_length=400)]


Quotes = Annotated[list[Evidence], Field(min_length=1, max_length=3)]


class Affected(FrozenModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    kind: Literal[AFFECTED_KINDS]
    evidence: Quotes


class Dimension(FrozenModel):
    dimension: Literal[tuple(DIMENSIONS)]
    how: Short
    evidence: Quotes


class Magnitude(FrozenModel):
    text: Annotated[str, Field(min_length=1, max_length=200)]
    evidence: Evidence


class Scope(FrozenModel):
    reach: Literal[REACH]
    magnitudes: Annotated[list[Magnitude], Field(max_length=4)]


class Annotation(FrozenModel):
    report_kind: Literal[tuple(REPORT_KINDS)]
    event_type: Literal[tuple(EVENT_TYPES)] | None
    change: Text
    change_evidence: Annotated[list[Evidence], Field(max_length=3)]
    affected: Annotated[list[Affected], Field(max_length=6)]
    dimensions: Annotated[list[Dimension], Field(max_length=6)]
    scope: Scope
    ambiguities: Annotated[list[Short], Field(max_length=5)]
    missing: Annotated[list[Short], Field(max_length=5)]
    verdict: Literal[VERDICTS]
    explanation: Text

    @model_validator(mode="after")
    def _consistent(self):
        if (self.report_kind == "development") != (self.event_type is not None):
            raise ValueError("event_type is given for a development and only for one")
        names = [row.dimension for row in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("each dimension is named at most once")
        return self


class AnnotationRejected(ValueError):
    """An annotation that is not the schema's: nothing of it is used."""


def validated(payload: object) -> dict:
    """The annotation as the schema reads it (JSON-shaped), or AnnotationRejected with the problems in words."""
    try:
        return Annotation.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(part) for part in error['loc']) or 'annotation'}: {error['msg']}"
                             for error in exc.errors()[:6])
        raise AnnotationRejected(f"The annotation does not follow {ANNOTATION_VERSION}: {problems}") from None


def response_schema() -> dict:
    """The structured output format sent to the model. Structured outputs reject string-length and item-count
    constraints, so the prompt states them and ``validated`` enforces them on receipt."""
    text = {"type": "string"}
    evidence = {"type": "object", "additionalProperties": False, "required": ["report", "quote"],
                "properties": {"report": text, "quote": text}}
    quotes = {"type": "array", "items": evidence}
    return {"type": "object", "additionalProperties": False, "required": [
        "report_kind", "event_type", "change", "change_evidence", "affected", "dimensions", "scope", "ambiguities",
        "missing", "verdict", "explanation"], "properties": {
        "report_kind": {"type": "string", "enum": list(REPORT_KINDS)},
        "event_type": {"anyOf": [{"type": "string", "enum": list(EVENT_TYPES)}, {"type": "null"}]},
        "change": text, "change_evidence": quotes,
        "affected": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "kind", "evidence"],
            "properties": {"name": text, "kind": {"type": "string", "enum": list(AFFECTED_KINDS)},
                           "evidence": quotes}}},
        "dimensions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["dimension", "how", "evidence"],
            "properties": {"dimension": {"type": "string", "enum": list(DIMENSIONS)}, "how": text,
                           "evidence": quotes}}},
        "scope": {"type": "object", "additionalProperties": False, "required": ["reach", "magnitudes"],
                  "properties": {"reach": {"type": "string", "enum": list(REACH)}, "magnitudes": {
                      "type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["text", "evidence"],
                                                 "properties": {"text": text, "evidence": evidence}}}}},
        "ambiguities": {"type": "array", "items": text}, "missing": {"type": "array", "items": text},
        "verdict": {"type": "string", "enum": list(VERDICTS)}, "explanation": text}}


# ---------------------------------------------------------------- evidence

FOLD = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "“": '"',
                      "”": '"', "„": '"', "″": '"', "‐": "-", "‑": "-", "‒": "-",
                      "–": "-", "—": "-", "−": "-", "­": None})
FIELDS = ("title", "excerpt", "text")
MIN_QUOTE_WORDS = 2


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(FOLD).split()).casefold()


def _quotes(annotation: dict):
    """Every (where, evidence) pair the annotation names, in a fixed order."""
    for index, row in enumerate(annotation["change_evidence"]):
        yield f"change_evidence[{index}]", row
    for index, row in enumerate(annotation["affected"]):
        for number, evidence in enumerate(row["evidence"]):
            yield f"affected[{index}].evidence[{number}]", evidence
    for index, row in enumerate(annotation["dimensions"]):
        for number, evidence in enumerate(row["evidence"]):
            yield f"dimensions[{index}].evidence[{number}]", evidence
    for index, row in enumerate(annotation["scope"]["magnitudes"]):
        yield f"scope.magnitudes[{index}].evidence", row["evidence"]


def check_evidence(annotation: dict, sources: dict[str, dict]) -> dict:
    """Where each quote was found in the material (``sources``: report ID -> {title, excerpt, text}, each text or None),
    and what the found quotes support."""
    folded = {report: {field: normalise(row[field]) for field in FIELDS if row.get(field)}
              for report, row in sources.items()}
    checked = []
    for where, evidence in _quotes(annotation):
        quote = normalise(evidence["quote"])
        row = {"where": where, "report": evidence["report"], "found": False, "field": None, "position": None,
               "problem": None}
        if evidence["report"] not in folded:
            row["problem"] = "names a report that is not in the material"
        elif len(quote.split()) < MIN_QUOTE_WORDS:
            row["problem"] = f"shorter than {MIN_QUOTE_WORDS} words"
        else:
            for field, held in folded[evidence["report"]].items():
                position = held.find(quote)
                if position >= 0:
                    row.update(found=True, field=field, position=position)
                    break
            else:
                row["problem"] = "not found in that report's headline, excerpt or text"
        checked.append(row)
    found = {row["where"] for row in checked if row["found"]}

    def supported(prefix: str) -> bool:
        return any(where.startswith(prefix) for where in found)
    dimensions = [row["dimension"] for index, row in enumerate(annotation["dimensions"])
                  if supported(f"dimensions[{index}].")]
    return {"evidence_version": EVIDENCE_VERSION, "quotes": checked, "found": len(found),
            "not_found": len(checked) - len(found), "change_supported": supported("change_evidence"),
            "supported_dimensions": dimensions,
            "unsupported_dimensions": [row["dimension"] for row in annotation["dimensions"]
                                       if row["dimension"] not in dimensions],
            "supported_affected": [row["name"] for index, row in enumerate(annotation["affected"])
                                   if supported(f"affected[{index}].")],
            "supported_magnitudes": [row["text"] for index, row in enumerate(annotation["scope"]["magnitudes"])
                                     if f"scope.magnitudes[{index}].evidence" in found]}


# ---------------------------------------------------------------- the decisions

KIND_WORDS = {key: value.split(":")[0] for key, value in REPORT_KINDS.items()}


def decide(annotation: dict, evidence: dict) -> dict:
    """The relevance decision (DECISION_VERSION) from an annotation and its evidence check: {state, reasons}."""
    verdict, kind = annotation["verdict"], annotation["report_kind"]
    dimensions = evidence["supported_dimensions"]
    if verdict == "insufficient_information":
        return {"decision_version": DECISION_VERSION, "state": "insufficient",
                "reasons": ["The assessment found that its sources say too little to tell."]}
    if verdict == "relevant":
        problems = []
        if kind != "development":
            problems.append(f"It was judged relevant, but it is {KIND_WORDS[kind]}, not a reported development.")
        if not evidence["change_supported"]:
            problems.append("What changed is not quoted from its sources.")
        if not dimensions:
            problems.append("No economic dimension is supported by a quote from its sources.")
        if problems:
            return {"decision_version": DECISION_VERSION, "state": "needs_review", "reasons": problems}
        return {"decision_version": DECISION_VERSION, "state": "relevant", "reasons": [
            f"A reported development whose sources support {len(dimensions)} economic "
            f"dimension{'s' if len(dimensions) != 1 else ''}: {', '.join(dimensions)}."]}
    if kind == "development" and len(dimensions) >= 2:
        return {"decision_version": DECISION_VERSION, "state": "needs_review", "reasons": [
            f"It was judged outside the scope, but it is a reported development whose sources support "
            f"{len(dimensions)} economic dimensions ({', '.join(dimensions)})."]}
    return {"decision_version": DECISION_VERSION, "state": "outside_scope",
            "reasons": [f"Judged outside the economic news's scope: {KIND_WORDS[kind]}."]}


EVENT_POINTS = {"policy_decision": 1.0, "enforcement": 0.75, "official_data": 0.75, "agreement": 0.75,
                "disruption": 0.75, "corporate_action": 0.5, "policy_proposal": 0.5, "official_statement": 0.25,
                "other_development": 0.25}
REACH_POINTS = {"global": 0.75, "international": 0.75, "national": 0.5, "regional": 0.25, "sector": 0.25,
                "company": 0.0, "local": 0.0, "unclear": 0.0}
SIZE_POINTS = 0.25
EVENT_WORDS = {"policy_decision": "an adopted policy decision", "policy_proposal": "a policy proposal",
               "enforcement": "an enforcement action or ruling", "official_data": "a release of official data",
               "official_statement": "an official statement", "agreement": "an agreement",
               "corporate_action": "a corporate action", "disruption": "a disruption",
               "other_development": "a development"}
REACH_WORDS = {"global": "global reach", "international": "international reach", "national": "national reach",
               "regional": "regional reach", "sector": "the reach of a sector", "company": "the reach of a company",
               "local": "local reach", "unclear": "unclear reach"}


def importance(annotation: dict, evidence: dict) -> dict:
    """Editorial importance (IMPORTANCE_VERSION): fixed points from the annotation's categories, never a model's
    number. Only a relevant development has one."""
    event = annotation["event_type"] or "other_development"
    sized = bool(evidence["supported_magnitudes"])
    points = EVENT_POINTS[event] + REACH_POINTS[annotation["scope"]["reach"]] + (SIZE_POINTS if sized else 0.0)
    text = (f"Assessed as {EVENT_WORDS[event]} of {REACH_WORDS[annotation['scope']['reach']]}"
            + (", and its sources state its size." if sized else "."))
    return {"importance_version": IMPORTANCE_VERSION, "points": round(points, 3), "text": text,
            "level": "high" if points >= 1.5 else "moderate" if points >= 0.75 else "low"}


# ---------------------------------------------------------------- a story's relevance, from saved records

BASIS_LABEL = {
    "editor": "Judged by an editor.",
    "model": "Assessed by AI in this application from its sources; not reviewed by an editor.",
    "assisted": "Assessed with an AI assistant from its sources; not reviewed by an editor.",
    "synthetic": "A SYNTHETIC assessment for tests and the demo.",
}
STATE_TEXT = {
    "relevant": "In the economic news.",
    "outside_scope": "Not in the economic news: assessed as outside its scope.",
    "insufficient": "Its sources say too little to tell whether it reports an economic development.",
    "needs_review": "Its assessment was not clear-cut; an editor has not decided yet.",
    "unavailable": "Its assessment could not be completed; an editor has not decided yet.",
    "restricted": ("Not assessed: its publisher's terms do not allow its text to be used by an AI system, and an "
                   "editor has not judged it."),
    "pending": "Not assessed yet.",
}


def _annotation_view(row: dict) -> dict:
    """What every view may show of a saved annotation."""
    decision = decide(row["annotation"], row["evidence"])
    shown = {"event_id": row["event_id"], "method": row["method"], "material_sha256": row["material_sha256"],
             "at": row["at"], "versions": row["versions"], "decision": decision,
             "report_kind": row["annotation"]["report_kind"], "event_type": row["annotation"]["event_type"],
             "change": row["annotation"]["change"], "verdict": row["annotation"]["verdict"],
             "explanation": row["annotation"]["explanation"],
             "dimensions": [{"dimension": item["dimension"], "how": item["how"],
                             "supported": item["dimension"] in row["evidence"]["supported_dimensions"]}
                            for item in row["annotation"]["dimensions"]],
             "reach": row["annotation"]["scope"]["reach"],
             "magnitudes": row["evidence"]["supported_magnitudes"],
             "ambiguities": row["annotation"]["ambiguities"], "missing": row["annotation"]["missing"],
             "evidence": {key: row["evidence"][key] for key in ("found", "not_found", "change_supported")}}
    if decision["state"] == "relevant":
        shown["importance"] = importance(row["annotation"], row["evidence"])
    return shown


def relevance_of(folded: dict, story: dict) -> dict:
    """A story's relevance as the saved records decide it now: an editor's judgement, else the latest annotation of
    its current material (or, flagged, of earlier material), else a failed attempt, else restricted or pending."""
    story_id, material = story["story_id"], story["material"]
    reviews = folded.get("relevance_reviews", {}).get(story_id, [])
    review = reviews[-1] if reviews and reviews[-1]["verdict"] != "cleared" else None
    rows = folded.get("relevance", {}).get(story_id, [])
    current = [row for row in rows if row["material_sha256"] == material["material_sha256"]]
    annotated = [row for row in current if row["outcome"] == "annotated"]
    earlier = [row for row in rows if row["outcome"] == "annotated" and row not in current]
    chosen = annotated[-1] if annotated else (earlier[-1] if earlier else None)
    failed = current[-1] if current and current[-1]["outcome"] == "failed" and not annotated else None
    shown = _annotation_view(chosen) if chosen else None
    base = {"relevance_version": RELEVANCE_VERSION, "annotation": shown,
            "current": (chosen["material_sha256"] == material["material_sha256"]) if chosen else None,
            "review": {key: review[key] for key in ("verdict", "reason", "actor", "at", "material_sha256")}
            if review else None,
            "failure": {"at": failed["at"], "detail": failed["evidence"].get("detail"),
                        "method": failed["method"]} if failed else None,
            "assessable": bool(material["reports"])}
    if review is not None:
        state = VERDICT_STATE[review["verdict"]]
        rated = shown["importance"] if state == "relevant" and shown and "importance" in shown else None
        return {**base, "state": state, "basis": "editor", "explanation": review["reason"], "importance": rated}
    if shown is not None:
        decision = shown["decision"]
        explanation = shown["explanation"] if decision["state"] in ("relevant", "outside_scope") else \
            " ".join(decision["reasons"])
        return {**base, "state": decision["state"], "basis": chosen["method"], "explanation": explanation,
                "importance": shown.get("importance")}
    if failed is not None:
        return {**base, "state": "unavailable", "basis": failed["method"], "importance": None,
                "explanation": failed["evidence"].get("detail") or "The assessment failed."}
    state = "pending" if material["reports"] else "restricted"
    return {**base, "state": state, "basis": None, "explanation": STATE_TEXT[state], "importance": None}


def reader_view(relevance: dict) -> dict:
    """What a reader is told: the state in words, who decided it and why, and the supported dimensions."""
    annotation = relevance["annotation"]
    state = relevance["state"]
    shown = {"state": state, "statement": STATE_TEXT[state],
             "basis": relevance["basis"] if relevance["basis"] in BASIS_LABEL else None,
             "basis_label": BASIS_LABEL.get(relevance["basis"]), "explanation": None, "change": None,
             "dimensions": [], "missing": [], "current": relevance["current"]}
    if state in ("relevant", "outside_scope", "insufficient"):
        shown["explanation"] = relevance["explanation"]
    if annotation is not None and state == "relevant" and relevance["basis"] != "editor":
        shown.update(change=annotation["change"], missing=annotation["missing"][:3],
                     dimensions=[{"dimension": row["dimension"], "how": row["how"]}
                                 for row in annotation["dimensions"] if row["supported"]])
    return shown


# ---------------------------------------------------------------- the explicit writes

def record(newsroom: ns.Newsroom, story_id: str, material_sha256: str, entry: dict, actor: str, moment: datetime,
           key: str) -> tuple[dict, bool]:
    """Save one annotation (``entry``: method, outcome, annotation or None, evidence, versions, preparation) of the
    material the caller checked it against. Repeating the key returns the first result."""
    if entry["method"] not in METHODS or entry["outcome"] not in ("annotated", "failed") or \
            (entry["outcome"] == "annotated") != (entry["annotation"] is not None):
        raise AccountsRefused(422, "invalid_request", "An annotation is annotated with content, or a failed attempt.")
    payload = {"story_id": story_id, "material_sha256": material_sha256, **entry}
    with newsroom.writing() as connection:
        done = ns.operation(connection, key, "relevance", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM stories WHERE story_id = ?", (story_id,)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        at = ns.stamp(moment)
        cursor = connection.execute(
            "INSERT INTO relevance_annotations (story_id, material_sha256, method, outcome, annotation, evidence, "
            "versions, preparation, actor, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (story_id, material_sha256, entry["method"], entry["outcome"],
             json.dumps(entry["annotation"], sort_keys=True) if entry["annotation"] is not None else None,
             json.dumps(entry["evidence"], sort_keys=True), json.dumps(entry["versions"], sort_keys=True),
             json.dumps(entry["preparation"], sort_keys=True), actor, at))
        result = {"story_id": story_id, "event_id": cursor.lastrowid, "outcome": entry["outcome"],
                  "state": decide(entry["annotation"], entry["evidence"])["state"]
                  if entry["annotation"] is not None else "unavailable", "at": at}
        ns.record_operation(connection, key, "relevance", actor, payload, result, at)
    return result, True


def review(newsroom: ns.Newsroom, story_id: str, form: dict, material_sha256: str, actor: str,
           moment: datetime) -> tuple[dict, bool]:
    """An editor's judgement of a story's relevance, with a reason (``form``: verdict, reason, idempotency_key);
    ``cleared`` withdraws an earlier judgement so the assessment decides again."""
    verdict = form.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        raise AccountsRefused(422, "invalid_request", f"The verdict is one of {', '.join(REVIEW_VERDICTS)}.")
    reason = checked_reason(form.get("reason"))
    payload = {"story_id": story_id, "verdict": verdict, "reason": reason, "material_sha256": material_sha256}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "relevance-review", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM stories WHERE story_id = ?", (story_id,)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO relevance_reviews (story_id, material_sha256, verdict, reason, actor, at) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (story_id, material_sha256, verdict, reason, actor, at))
        result = {"story_id": story_id, "verdict": verdict, "reason": reason, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "relevance-review", actor, payload, result, at)
    return result, True

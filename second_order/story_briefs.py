"""Shared briefs: a story's short summary and analysis, prepared in advance and read by every user (story-brief-0.1).

A brief is written from material (story-material-0.1): the story's reports whose publishers allow that use
(news_registry: public-domain official releases, reuse encouraged with a credit, or a newsroom's public-domain or
openly licensed text, news-registry-0.5), as the feeds give them: the
headline and the feed's excerpt, with the address and the stated publication time. The material says what it is and
what it is not: an excerpt is discovery metadata, not the publication, so a brief prepared from it never presents itself
as an analysis of the full article. Reports whose publishers grant no such use are listed and linked on the story page
but never used, and the material names them.

The content keeps reported facts apart from possible implications: ``summary`` and ``facts`` say what was reported,
each fact citing the material reports it rests on; ``implications`` are why it may matter, phrased as possibilities;
``themes`` name sectors, companies or themes with the basis in the reports; ``uncertainties`` and ``missing`` say what
is not known. A fixed lexical guard (brief-guard-0.3) refuses publication of advice to trade, and of causal or certain
claims that the brief makes itself; it is a check of words, not of truth. Whether a person read a version is
recorded separately (``review``), never assumed.

From story-brief-0.3 a version may also hold its story's economic explanation (``economics``, story_economics): why
the development may matter economically, through which channels and for whom, resting on the same material, a
recorded context bundle and sourced framework notes, with its derived figures computed in code. It is checked against
that evidence before it is saved, its own guard (econ-guard-0.1) stops publication, and the version records how it was
prepared (the analysis, calculation and framework versions, and the bundle). Versions without one keep their shape.

From story-brief-0.4 a version may record its **claims** (brief_claims): who says what a fact, the development or a
figure relies on, how it was put (stated, conditional, planned, a view or a question) and on what condition, each with
its exact words in its source; its facts then cite the claims they rest on (``facts[].claims``). A version without
claims keeps the earlier shape and is read as before; readers are shown the claims a version records ("Who says what").

Versions are append-only (newsroom_store): an edit is a new version naming the one it was based on; a publication names
one version; users read the latest publication. Preparing, saving and publishing are the operator's explicit actions;
reading a brief only reads.

Authorship is recorded as it happened (story-brief-0.2). ``editorial`` and ``extract`` versions are a person's work;
``model`` versions were drafted by an AI model in this application (the request, model and reported usage are kept);
``assisted`` versions were written with an AI assistant outside this application (the tool, and the model only when the
operator declares it, are kept; nothing else is invented). Whether a person read a version is a separate, explicit
record (``review``): publishing is not reviewing, and a reader is told which. A recorded assessment can state that a
story's material, by its SHA-256, cannot support a useful brief (``assess``), so the story says so instead of carrying a
thin one.
"""
from datetime import datetime
import json
import re

from . import brief_claims, newsroom_store as ns
from .accounts import AccountsRefused
from .news_stories import checked_reason

BRIEF_VERSION = "story-brief-0.4"  # 0.3: an optional economic explanation; 0.4: optional claims (brief_claims).
MATERIAL_VERSION = "story-material-0.1"  # Headlines and feed excerpts only: unchanged, so its SHA-256 is too.
TEXT_MATERIAL_VERSION = "story-material-0.2"  # A material with at least one retained publication text (news_texts).
GUARD_VERSION = "brief-guard-0.3"  # 0.3: a simple question in an unknowns list is not a causal assertion.
FIELDS = ("headline", "summary", "facts", "implications", "themes", "uncertainties", "missing")
LIMITS = {"headline": 160, "summary": 700, "item": 300, "theme_name": 60, "theme_basis": 200}
COUNTS = {"facts": (1, 6), "implications": (0, 3), "themes": (0, 6), "uncertainties": (0, 5), "missing": (0, 5)}
THEME_KINDS = ("sector", "company", "theme")
EDITOR_METHODS = ("editorial", "extract")
AI_METHODS = ("model", "assisted")
METHODS = (*EDITOR_METHODS, *AI_METHODS, "synthetic")
METHOD_LABEL = {
    "editorial": "Written by an editor from the material below.",
    "extract": "Compiled from the reports' own words and completed by an editor.",
    "model": "Drafted by an AI model in this application from the material below.",
    "assisted": "Written with an AI assistant from the material below.",
    "synthetic": "SYNTHETIC example written for this demonstration; it is not about real events.",
}
AUTHORSHIP = {"editorial": "editor", "extract": "editor", "model": "ai_model", "assisted": "ai_assistant",
              "synthetic": "synthetic"}
VERDICTS = ("insufficient", "sufficient")
MAX_TOOL = 80
ADVICE = re.compile(r"\b(investors should|you should|we recommend|recommend(?:s|ed)? (?:buying|selling|holding)|"
                    r"price target|target price|(?:buy|sell|hold) (?:rating|signal|recommendation)|take profits?|"
                    r"stop[- ]loss|go long|go short|overweight|underweight|short[- ]sell\w*)\b", re.IGNORECASE)
TRADE = re.compile(r"\b(buy|buying|sell|selling|short|shorting|hedge|hedging|bet on|bet against)\b", re.IGNORECASE)
CAUSAL = re.compile(r"\b(will cause|caused|causes|causing|led to|leads to|drove|drives|resulted in|results in|"
                    r"due to|because of|as a result of|triggered|forced)\b", re.IGNORECASE)
ATTRIBUTED = re.compile(r"\b(said|says|according to|stated|states|reported|reports|announced|wrote|told|cited)\b",
                        re.IGNORECASE)
HEDGE = re.compile(r"\b(may|might|could|would|can|if|possible|possibly|potentially|whether)\b", re.IGNORECASE)
CERTAIN = re.compile(r"\b(certainly|definitely|guarantee[sd]?|inevitabl[ey]|undoubtedly|surely)\b", re.IGNORECASE)
GUARANTEE_AUXILIARY = r"(?:may|might|could|can|would|will|should|must|is|are|was|were|has|have|had)"
GUARANTEE_SUBJECT = re.compile(r"^\s+" + GUARANTEE_AUXILIARY + r"\b", re.IGNORECASE)
GUARANTEED_CREDIT = re.compile(
    r"^\s+(?:loans?|credit|debt|bonds?|deposits?)(?=\s+(?:" + GUARANTEE_AUXILIARY +
    r"|to|for|from|of|with|under|by)\b|[,;:.]|$)", re.IGNORECASE)
SENTENCE = re.compile(r"[^.!?]+[.!?]*")
UNKNOWN_QUESTION = re.compile(r"^\s*(?:which|what|who)\b", re.IGNORECASE)
QUESTION_CLAUSE = re.compile(r"[,;:]|\b(?:and|but|because|although|however|therefore|while|yet|so|whereas)\b",
                             re.IGNORECASE)


def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_brief", detail)


# ---------------------------------------------------------------- material

def _text_row(state: dict | None) -> dict | None:
    if not state or state["state"] not in ("full_text", "partial_text"):
        return None
    return {key: state[key] for key in ("state", "text_sha256", "characters", "retrieved_at", "url", "extractor",
                                        "partial_reason")}


def _statement(rows: list[dict]) -> tuple[str, str]:
    """(coverage, statement): what the material holds, in words. The statement is part of the material's SHA-256:
    changing its words makes every brief of such material one of "earlier material", so its wording is pinned by
    tests/test_news_texts.py and changes only with a new material version."""
    count = len(rows)
    with_text = [row for row in rows if row.get("text")]
    excerpts = sum(1 for row in rows if row["excerpt"])
    plural = lambda number, word: f"{number} {word}{'s' if number != 1 else ''}"  # noqa: E731
    if not with_text:
        parts = "headlines and feed excerpts" if excerpts else "headlines"
        return ("headlines_and_excerpts" if excerpts else "headlines",
                f"Prepared from the {parts} of {plural(count, 'report')} as the feeds gave them. The full publications "
                "were not read, so anything they add is not reflected here.")
    partial = [row for row in with_text if row["text"]["state"] == "partial_text"]
    if len(with_text) == count and not partial:
        return "full_text", (f"Prepared from the full text of {plural(count, 'official publication')}, as this server "
                             "retrieved them from the publishers' own pages.")
    text = (f"Prepared from the text of {len(with_text)} of {plural(count, 'report')} as this server retrieved them "
            "from the publishers' own pages")
    if len(with_text) < count:
        text += "; the others as their feeds gave them (headline and excerpt), whose publications were not read"
    if partial:
        text += "; " + "; ".join(f"from {row['publisher']}, part was left out ({row['text']['partial_reason']})"
                                 for row in partial)
    return "partial_text", text + "."


INDEXED_REASON = ("Listed from the GDELT index of news coverage: its headline and link only; its text is not held, "
                  "and nothing of it is used for summaries or analysis.")


def material(story_id: str, reports: list[dict], texts: dict[str, dict] | None = None) -> dict:
    """What a brief or a deeper analysis of this story may be prepared from, and what it leaves out and why. ``texts``
    holds each report's publication text state (news_texts.text_state); a retained text is named by its SHA-256, so
    the material changes when a text is added."""
    used = sorted((report for report in reports if report["material"] == "permitted"),
                  key=lambda report: (report["at"], report["entry_id"]))
    left = [{"entry_id": report["entry_id"], "publisher": report["publisher"], "title": report["title"],
             "link": report["link"], "reason": INDEXED_REASON if report.get("indexed") else (
                 "Its publisher's terms grant no use for summaries or analysis, so it is listed and linked but not "
                 "used.")}
            for report in sorted(reports, key=lambda row: (row["at"], row["entry_id"]))
            if report["material"] != "permitted"]
    rows = [{"entry_id": report["entry_id"], "version_sha256": report["version_sha256"],
             "publisher": report["publisher"], "role": report["role"], "title": report["title"],
             "excerpt": report["excerpt"], "link": report["link"], "published": report["published"]["as_stated"],
             "published_utc": report["published"]["utc"], "attribution": report["attribution"],
             "synthetic": report["synthetic"]} for report in used]
    for row in rows:
        text = _text_row((texts or {}).get(row["entry_id"]))
        if text:
            row["text"] = text
    if not rows:
        coverage, statement = "none", ("None of this story's reports may be used for a summary or an analysis: their "
                                       "publishers' terms grant no such use. Read them at their sources.")
    else:
        coverage, statement = _statement(rows)
    version = TEXT_MATERIAL_VERSION if any(row.get("text") for row in rows) else MATERIAL_VERSION
    body = {"material_version": version, "story_id": story_id, "reports": rows, "not_used": left,
            "coverage": coverage, "statement": statement}
    return {**body, "material_sha256": ns.sha256_of(body)}


# ---------------------------------------------------------------- content

def _text(value: object, limit: int, label: str, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise _refuse(f"{label} is text of {'1' if required else '0'} to {limit} characters.")
    return value.strip()


def _list(content: dict, name: str) -> list:
    low, high = COUNTS[name]
    value = content[name]
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _refuse(f"{name} holds {low} to {high} items.")
    return value


def checked_facts(rows: object, used: set[str], claims: list[dict] | None = None) -> list[dict]:
    """A brief's facts: one to six, each a text citing one or more of the material's reports; refused otherwise. In a
    version that records claims (``claims``, story-brief-0.4) each fact also names the claims it rests on (possibly
    none)."""
    shape = {"text", "reports"} if claims is None else {"text", "reports", "claims"}
    facts = []
    for index, fact in enumerate(_list({"facts": rows}, "facts"), start=1):
        if not isinstance(fact, dict) or set(fact) != shape or not isinstance(fact["reports"], list) or \
                not fact["reports"] or len(set(fact["reports"])) != len(fact["reports"]) or \
                any(entry not in used for entry in fact["reports"]):
            raise _refuse(f"Fact {index} has text and the material reports it rests on (one or more)"
                          + ("" if claims is None else ", and the claims it rests on (a list, possibly empty)") + ".")
        row = {"text": _text(fact["text"], LIMITS["item"], f"Fact {index}"), "reports": fact["reports"]}
        if claims is not None:
            row["claims"] = brief_claims.fact_claims(fact["claims"], claims, f"Fact {index}")
        facts.append(row)
    return facts


def checked_themes(rows: object) -> list[dict]:
    """A brief's themes: at most six, each a kind, a name and its basis in the reports; refused otherwise."""
    themes = []
    for index, row in enumerate(_list({"themes": rows}, "themes"), start=1):
        if not isinstance(row, dict) or set(row) != {"kind", "name", "basis"} or row["kind"] not in THEME_KINDS:
            raise _refuse(f"Theme {index} has a kind ({', '.join(THEME_KINDS)}), a name and its basis.")
        themes.append({"kind": row["kind"], "name": _text(row["name"], LIMITS["theme_name"], f"Theme {index}'s name"),
                       "basis": _text(row["basis"], LIMITS["theme_basis"], f"Theme {index}'s basis")})
    return themes


def checked_items(rows: object, name: str, label: str) -> list[str]:
    """A brief's uncertainties or missing information: texts, within their count; refused otherwise."""
    return [_text(row, LIMITS["item"], f"{label} {index}") for index, row in enumerate(_list({name: rows}, name),
                                                                                       start=1)]


def checked_content(content: object, used: set[str], basis: dict | None = None,
                    analysis_version: str | None = None) -> dict:
    """The brief's content in its exact shape, every fact citing material reports; refused otherwise. An economic
    explanation and claims (each optional) are checked against ``basis`` (story_economics.evidence); without one they
    are refused. An explanation is checked under the current analysis version, or under ``analysis_version`` to
    reproduce an earlier check."""
    if isinstance(content, dict) and "economics" in content and content["economics"] is None:
        content = {key: value for key, value in content.items() if key != "economics"}
    if not isinstance(content, dict) or set(content) - {"economics", "claims"} != set(FIELDS):
        raise _refuse(f"A brief has exactly: {', '.join(FIELDS)}, and optionally economics and claims.")
    claims = None
    if "claims" in content:
        if basis is None:
            raise _refuse("Claims are checked against the evidence they quote.")
        claims = brief_claims.checked(content["claims"], basis["sources"])
    facts = checked_facts(content["facts"], used, claims)
    implications = []
    for index, row in enumerate(_list(content, "implications"), start=1):
        if not isinstance(row, dict) or set(row) != {"text"}:
            raise _refuse(f"Implication {index} has exactly a text.")
        implications.append({"text": _text(row["text"], LIMITS["item"], f"Implication {index}")})
    themes = checked_themes(content["themes"])
    checked = {"headline": _text(content["headline"], LIMITS["headline"], "The headline"),
               "summary": _text(content["summary"], LIMITS["summary"], "The summary"), "facts": facts,
               "implications": implications, "themes": themes,
               "uncertainties": checked_items(content["uncertainties"], "uncertainties", "Uncertainty"),
               "missing": checked_items(content["missing"], "missing", "Missing information")}
    if claims is not None:
        checked["claims"] = claims
    if "economics" in content:
        from . import story_economics
        if basis is None:
            raise _refuse("An economic explanation is checked against the evidence it was prepared from.")
        checked["economics"] = story_economics.checked(content["economics"], facts, basis,
                                                       analysis_version or story_economics.ANALYSIS_VERSION, claims)
    return checked


def _certainty(text: str):
    """First assertion of certainty, skipping two narrow noun/adjective uses of financial guarantees.

    A guarantee followed directly by a finite auxiliary is a subject ("guarantees may help"), not the verb
    "guarantees returns". "Guaranteed loans" describes the credit, while "guaranteed bond returns" is still flagged.
    A noun never masks a later "certainly" or "is guaranteed to". Other ambiguous uses remain conservatively flagged.
    """
    for found in CERTAIN.finditer(text):
        word, tail = found.group(0).lower(), text[found.end():]
        if word in ("guarantee", "guarantees") and GUARANTEE_SUBJECT.match(tail):
            continue
        if word == "guaranteed" and GUARANTEED_CREDIT.match(tail):
            continue
        return found
    return None


def guard(content: dict) -> dict:
    """brief-guard-0.3: the words that refuse publication, each with where it was found."""
    findings = []

    def flag(where: str, rule: str, matched: str, detail: str) -> None:
        findings.append({"where": where, "rule": rule, "matched": matched, "detail": detail})

    places = [("headline", content["headline"]), ("summary", content["summary"])]
    places += [(f"facts[{index}]", row["text"]) for index, row in enumerate(content["facts"])]
    places += [(f"themes[{index}]", f"{row['name']} {row['basis']}") for index, row in enumerate(content["themes"])]
    places += [(f"uncertainties[{index}]", row) for index, row in enumerate(content["uncertainties"])]
    places += [(f"missing[{index}]", row) for index, row in enumerate(content["missing"])]
    implications = [(f"implications[{index}]", row["text"]) for index, row in enumerate(content["implications"])]
    for where, text in places + implications:
        found = ADVICE.search(text)
        if found:
            flag(where, "advice", found.group(0), "A brief never advises anyone to trade.")
    for where, text in places:
        for sentence in SENTENCE.findall(text):
            found = CAUSAL.search(sentence)
            # Only a single, simple interrogative in an unknowns field; never a summary/fact or a mixed clause.
            if found and where.startswith(("missing[", "uncertainties[")) and UNKNOWN_QUESTION.match(sentence) and \
                    not QUESTION_CLAUSE.search(sentence) and len(CAUSAL.findall(sentence)) == 1:
                continue
            if found and not ATTRIBUTED.search(sentence):
                flag(where, "causal_claim", found.group(0), "A cause may be reported as someone's statement, never "
                                                            "claimed by the brief itself.")
    for where, text in implications:
        for rule, pattern, detail in (("trade", TRADE, "An implication never speaks of trading."),
                                      ("causal_claim", CAUSAL, "An implication is a possibility, never a cause."),
                                      ("certainty", CERTAIN, "An implication is a possibility, never a certainty.")):
            found = _certainty(text) if rule == "certainty" else pattern.search(text)
            if found:
                flag(where, rule, found.group(0), detail)
        if not HEDGE.search(text):
            flag(where, "unhedged", "", "An implication says what may follow (may, might, could, would, if, …).")
    return {"guard_version": GUARD_VERSION, "findings": findings,
            "statement": "A check of words, not of truth: passing it does not show that a brief is right."}


def publishable(content: dict, checked: dict) -> list[str]:
    """What still stops a version from being published."""
    problems = [f"{row['where']}: {row['detail']} (“{row['matched']}”)" if row["matched"] else
                f"{row['where']}: {row['detail']}" for row in checked["findings"]]
    if not content["implications"]:
        problems.append("A published brief says why it may matter: at least one implication.")
    if not content["uncertainties"] and not content["missing"]:
        problems.append("A published brief says what is uncertain or missing: at least one item.")
    return problems


def extract_draft(story: dict, prepared: dict) -> dict:
    """A $0 starting draft from the material's own words (no model): the facts are the reports' headlines, credited;
    the editors write why it may matter and what is uncertain before publishing."""
    rows = prepared["reports"]
    if not rows:
        raise AccountsRefused(409, "no_material", prepared["statement"])
    first = rows[0]
    lead = (first["excerpt"] or first["title"]).strip()
    sentence = SENTENCE.match(lead)
    summary = f"{first['publisher']}: {(sentence.group(0) if sentence else lead).strip()}"[:LIMITS["summary"]]
    return {"headline": story["title"][:LIMITS["headline"]], "summary": summary,
            "facts": [{"text": f"{row['publisher']}: {row['title']}"[:LIMITS["item"]], "reports": [row["entry_id"]]}
                      for row in rows[:COUNTS["facts"][1]]],
            "implications": [], "themes": [],
            "uncertainties": [], "missing": ["The full publications were not read; only their headlines and the feeds' "
                                             "excerpts were."]}


# ---------------------------------------------------------------- versions and publications

def assistant_preparation(tool: object, model: object, actor: str, note: str = "") -> dict:
    """The provenance of a version written with an AI assistant outside this application, as the operator declares it:
    the tool, the model only when they name it, and never usage or cost figures this application did not see."""
    if not isinstance(tool, str) or not tool.strip() or len(tool) > MAX_TOOL or \
            (model is not None and (not isinstance(model, str) or not model.strip() or len(model) > MAX_TOOL)):
        raise _refuse(f"An assisted version names its tool (and optionally its model), each of 1 to {MAX_TOOL} "
                      "characters.")
    return {"assistant": {"tool": tool.strip(), "model": model.strip() if model else None, "declared_by": actor,
                          "note": note}, "model": None, "cost": None}


def merged(findings: list[dict], more: list[dict]) -> list[dict]:
    """Findings with more added, each (where, rule, matched) once: a two-stage draft's coherence and econ_fidelity
    may both find the same reference in a brief's text."""
    rows, seen = list(findings), {(row["where"], row["rule"], row["matched"]) for row in findings}
    for row in more:
        if (row["where"], row["rule"], row["matched"]) not in seen:
            seen.add((row["where"], row["rule"], row["matched"]))
            rows.append(row)
    return rows


def add_version(newsroom: ns.Newsroom, story_id: str, form: dict, prepared: dict, actor: str, moment: datetime,
                method: str | None = None, preparation: dict | None = None, basis: dict | None = None,
                findings: list[dict] | None = None, analysis_version: str | None = None) -> tuple[dict, bool]:
    """Save a new brief version from the material as it is now. ``form``: content, method (editorial or extract),
    based_on (a version or null), idempotency_key. A model draft (brief_drafting), an assisted draft (with
    assistant_preparation) or a SYNTHETIC demo brief passes its own ``method`` and ``preparation``. An economic
    explanation is checked against ``basis`` (story_economics.evidence; by default the material's own headlines and
    excerpts). Guard findings are recorded with the version; they stop only publication. ``findings``: further
    checks of the same kind made by the caller (a two-stage draft's coherence, brief_stages), recorded with them, and
    econ_fidelity's (references, goods classifications, scale words), with its version, for every new version."""
    method = method or form.get("method")
    if method not in METHODS:
        raise _refuse(f"A version's method is one of {', '.join(METHODS)}.")
    if method not in EDITOR_METHODS and preparation is None:
        raise _refuse(f"An editor's version is {' or '.join(EDITOR_METHODS)}.")
    if method == "assisted" and not isinstance((preparation or {}).get("assistant"), dict):
        raise _refuse("An assisted version records the assistant it was written with.")
    if method == "synthetic" and not all(row["synthetic"] for row in prepared["reports"]):
        raise _refuse("A SYNTHETIC brief is only written about SYNTHETIC reports.")
    if not prepared["reports"]:
        raise AccountsRefused(409, "no_material", prepared["statement"])
    used = {row["entry_id"] for row in prepared["reports"]}
    submitted = form.get("content")
    if isinstance(submitted, dict) and (submitted.get("economics") is not None or "claims" in submitted) and \
            basis is None:
        from . import story_economics
        basis = story_economics.evidence(prepared)
    content = checked_content(submitted, used, basis, analysis_version)
    based_on = form.get("based_on")
    if based_on is not None and (isinstance(based_on, bool) or not isinstance(based_on, int)):
        raise _refuse("based_on is null or a version of this story's brief.")
    payload = {"story_id": story_id, "content": content, "method": method, "based_on": based_on,
               "material_sha256": prepared["material_sha256"]}
    checked = guard(content)
    analysis = None
    if "economics" in content:
        from . import story_economics
        checked["findings"] += story_economics.findings(content["economics"], basis)
        checked["economics_guard_version"] = story_economics.GUARD_VERSION
        analysis = story_economics.analysis_record(basis, content["economics"]["analysis_version"])
    from . import econ_fidelity
    checked["findings"] = merged(checked["findings"], list(findings or []) + econ_fidelity.findings(
        content, basis if "economics" in content or "claims" in content else None))
    checked["fidelity_version"] = econ_fidelity.FIDELITY_VERSION
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "brief", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM stories WHERE story_id = ?", (story_id,)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        versions = [row["version"] for row in connection.execute("SELECT version FROM briefs WHERE story_id = ?",
                                                                 (story_id,))]
        if based_on is not None and based_on not in versions:
            raise _refuse("based_on names a version this story's brief does not have.")
        version = max(versions, default=0) + 1
        at = ns.stamp(moment)
        record = {"method": method, "prepared_by": actor, "prepared_at": at, "based_on": based_on,
                  "statement": METHOD_LABEL[method], **(preparation or {"model": None, "cost": None})}
        if analysis is not None:
            record["analysis"] = analysis
        connection.execute("INSERT INTO briefs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            story_id, version, based_on, method, ns.canonical(content), ns.sha256_of(content),
            ns.canonical(prepared), prepared["material_sha256"], ns.canonical(record), ns.canonical(checked), actor,
            at))
        result = {"story_id": story_id, "version": version, "guard": checked,
                  "publishable": not publishable(content, checked), "at": at}
        ns.record_operation(connection, form["idempotency_key"], "brief", actor, payload, result, at)
    return result, True


def revalidate_version(newsroom: ns.Newsroom, story_id: str, form: dict, prepared: dict, actor: str,
                       moment: datetime, basis: dict | None = None) -> tuple[dict, bool]:
    """Append an unchanged version under the current guards, retaining its actual authorship and generation cost.

    The caller supplies the original application-shaped input (for a model version, replay its retained replies).
    Both material and checked content must match the old version: an explanation is checked under the analysis
    version it recorded (story-brief-0.4), so a later analysis version never makes unchanged content look changed.
    Never edits an earlier record, calls a provider, publishes, or claims a new generation or a human review. Repeating
    the same operation saves nothing new.
    """
    version, reason = form.get("version"), checked_reason(form.get("reason"))
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _refuse("version names an existing version to revalidate.")
    with newsroom.reading() as connection:
        old = connection.execute("SELECT * FROM briefs WHERE story_id = ? AND version = ?",
                                 (story_id, version)).fetchone()
    if old is None:
        raise AccountsRefused(404, "not_found", "This story's brief has no such version.")
    if prepared["material_sha256"] != old["material_sha256"]:
        raise AccountsRefused(409, "inputs_changed", "The material changed; this is not an unchanged revalidation.")
    recorded = (json.loads(old["content"]).get("economics") or {}).get("analysis_version")
    checked = checked_content(form.get("content"), {row["entry_id"] for row in prepared["reports"]}, basis, recorded)
    if ns.sha256_of(checked) != old["content_sha256"]:
        raise AccountsRefused(409, "content_changed", "Revalidation keeps the checked content exactly; an edit "
                                                     "needs a separately attributed new version.")
    previous = json.loads(old["preparation"])
    automatic = {"method", "prepared_by", "prepared_at", "based_on", "statement", "analysis"}
    preparation = {name: value for name, value in previous.items() if name not in automatic}
    preparation["revalidation"] = {
        "version": version, "content_sha256": old["content_sha256"],
        "previous_guard_version": json.loads(old["guard"])["guard_version"],
        "previous_guard_sha256": ns.sha256_of(json.loads(old["guard"])),
        "previous_preparation_sha256": ns.sha256_of(previous), "guard_version": GUARD_VERSION,
        "reason": reason, "actor": actor, "at": ns.stamp(moment),
        "additional_provider_requests": 0, "additional_usage_cost_usd": 0}
    findings = []
    if (previous.get("model") or {}).get("stages_version"):
        from . import brief_stages
        findings = brief_stages.coherence(checked, basis)
    done, created = add_version(newsroom, story_id, {
        "content": form["content"], "based_on": version, "idempotency_key": form.get("idempotency_key")},
        prepared, actor, moment, method=old["method"], preparation=preparation, basis=basis, findings=findings,
        analysis_version=recorded)
    return {**done, "revalidated_from": version}, created


def publish(newsroom: ns.Newsroom, story_id: str, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """Publish one version of a story's brief to every user, or withdraw the brief (version null). ``form``:
    version, reason, idempotency_key."""
    reason = checked_reason(form.get("reason"))
    version = form.get("version")
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise _refuse("version is a version of this story's brief, or null to withdraw it.")
    payload = {"story_id": story_id, "version": version, "reason": reason}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "publish", actor, payload)
        if done is not None:
            return done, False
        if version is not None:
            row = connection.execute("SELECT content, guard FROM briefs WHERE story_id = ? AND version = ?",
                                     (story_id, version)).fetchone()
            if row is None:
                raise AccountsRefused(404, "not_found", "This story's brief has no such version.")
            problems = publishable(json.loads(row["content"]), json.loads(row["guard"]))
            if problems:
                raise AccountsRefused(409, "brief_not_publishable", "This version cannot be published yet.",
                                      problems=problems)
        elif connection.execute("SELECT 1 FROM brief_publications WHERE story_id = ?", (story_id,)).fetchone() is None:
            raise AccountsRefused(409, "brief_not_publishable", "This story has no published brief to withdraw.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO brief_publications (story_id, version, actor, at, reason) VALUES (?, ?, ?, ?, ?)",
                           (story_id, version, actor, at, reason))
        result = {"story_id": story_id, "version": version, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "publish", actor, payload, result, at)
    return result, True


# ---------------------------------------------------------------- reviews and material assessments

def review(newsroom: ns.Newsroom, story_id: str, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """Record that ``actor`` read one version of a story's brief (an explicit statement; publishing is not one).
    ``form``: version, note (optional, up to 300 characters), idempotency_key."""
    version = form.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _refuse("version is a version of this story's brief.")
    note = _text(form.get("note", ""), LIMITS["item"], "The review's note", required=False)
    payload = {"story_id": story_id, "version": version, "note": note}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "review", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM briefs WHERE story_id = ? AND version = ?", (story_id, version)) \
                .fetchone() is None:
            raise AccountsRefused(404, "not_found", "This story's brief has no such version.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO brief_reviews (story_id, version, reviewer, at, note) VALUES (?, ?, ?, ?, ?)",
                           (story_id, version, actor, at, note))
        result = {"story_id": story_id, "version": version, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "review", actor, payload, result, at)
    return result, True


def assess(newsroom: ns.Newsroom, story_id: str, form: dict, prepared: dict, actor: str, moment: datetime,
           method: str = "editor") -> tuple[dict, bool]:
    """Record whether the story's material as it is now can support a useful brief. ``form``: material_sha256 (the
    material the judgement was made on; it must be the current one), verdict (insufficient or sufficient), reason,
    idempotency_key. ``method`` says who judged: an editor, an AI model or an AI assistant."""
    verdict = form.get("verdict")
    if verdict not in VERDICTS:
        raise _refuse(f"verdict is {' or '.join(VERDICTS)}.")
    if form.get("material_sha256") != prepared["material_sha256"]:
        raise AccountsRefused(409, "story_changed", "The story's material changed since it was judged; judge it again. "
                                                    "Nothing was recorded.")
    reason = checked_reason(form.get("reason"))
    payload = {"story_id": story_id, "material_sha256": prepared["material_sha256"], "verdict": verdict,
               "reason": reason, "method": method}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "assessment", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM stories WHERE story_id = ?", (story_id,)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO material_assessments (story_id, material_sha256, verdict, reason, method, "
                           "actor, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (story_id, prepared["material_sha256"], verdict, reason, method, actor, at))
        result = {"story_id": story_id, "verdict": verdict, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "assessment", actor, payload, result, at)
    return result, True


def correct_authorship(newsroom: ns.Newsroom, story_id: str, form: dict, preparation: dict, actor: str,
                       moment: datetime) -> tuple[dict, bool]:
    """A correction of who prepared a version: a new version with the same content and the same material as the one it
    corrects (so it says what it was really prepared from), under the corrected method (``preparation`` says how, and
    records what it corrects); the corrected version stays as it was recorded. ``form``: version, method (model or
    assisted), reason, idempotency_key. Publishing the correction is its own action."""
    version, method = form.get("version"), form.get("method")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _refuse("version is a version of this story's brief.")
    if method not in AI_METHODS or (method == "assisted" and not isinstance(preparation.get("assistant"), dict)):
        raise _refuse("A correction names an AI method (model or assisted) and, for assisted, the assistant.")
    reason = checked_reason(form.get("reason"))
    payload = {"story_id": story_id, "version": version, "method": method, "reason": reason,
               "preparation": preparation}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "correction", actor, payload)
        if done is not None:
            return done, False
        base = connection.execute("SELECT * FROM briefs WHERE story_id = ? AND version = ?", (story_id, version))\
            .fetchone()
        if base is None:
            raise AccountsRefused(404, "not_found", "This story's brief has no such version.")
        number = connection.execute("SELECT MAX(version) FROM briefs WHERE story_id = ?", (story_id,)).fetchone()[0] + 1
        at = ns.stamp(moment)
        record = {"method": method, "prepared_by": actor, "prepared_at": at, "based_on": version,
                  "statement": METHOD_LABEL[method], **preparation,
                  "corrects": {"version": version, "method": base["method"], "reason": reason}}
        connection.execute("INSERT INTO briefs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            story_id, number, version, method, base["content"], base["content_sha256"], base["material"],
            base["material_sha256"], ns.canonical(record), base["guard"], actor, at))
        result = {"story_id": story_id, "version": number, "corrects": version, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "correction", actor, payload, result, at)
    return result, True

"""Model drafts of a shared brief and its economic explanation (brief-drafting-0.2): two paid requests, each sent only
after its own visible cost decision.

Off unless the server was started with ``serve --enable-paid-briefs`` (or a test installs a simulated sender): without
a sender, a preview still shows the exact requests and their planning estimates, and an approval is refused before
anything is reserved.

The workflow (brief-prompt-12, brief_stages: stage 1 the evidence and figures, stage 2 the interpretation and brief) is
the operator's, step by step:

1. Preview (``POST .../drafting``, ``news drafting preview``) reads the story's material, its context bundle and the
   framework notes as they are now and shows the workflow: what each stage does, its output limit and planning
   estimate, the combined estimate, which stage has completed and what remains. It saves the next exact request once
   under data/newsroom/drafting/<request ID>/ (request.json, and preview.json with its frozen inputs: the material and
   its SHA-256, the context bundle, the framework, the stage's prompt, format, model, effort and output limit): stage 1
   (``brief-s1-``) until the evidence is validated for these inputs, then stage 2 (``brief-s2-``), prepared from the
   validated first stage and bound to it by SHA-256. A request ID is its own fingerprint, so the same inputs make the
   same request. Stage 2's bytes depend on stage 1's reply, so until then its estimate is planned from a request
   holding the largest first stage the limits allow: an estimate, not an exact request, and not authorized by
   approving stage 1.
2. Approval (``POST .../drafting/<request ID>/approval``, ``news drafting approve``) repeats that one request's SHA-256
   and its estimate with ``approve_paid_request: true``. The attempt is reserved write-once (one attempt per exact
   request, ever), the send is recorded as started, and the saved bytes are posted once: no retry, redirect, proxy,
   fallback model or second call. A transport error or timeout after sending is an unknown outcome, never sent again.
   - Stage 1: a reply that passes brief_stages.foundations is kept as foundations.json and recorded ``validated``; its
     stage 2 is then prepared (saved, not sent). A judgement that the material cannot support a brief is recorded as
     such (``insufficient``) and nothing more is prepared. Anything else (``invalid``, ``provider_error``,
     ``unknown``) is recorded, and no stage 2 is ever prepared from it.
   - Stage 2: refused before anything is reserved unless its inputs are still those it was prepared from: the
     material, the context bundle, the framework notes and the validated first stage. A reply that passes becomes an
     unpublished brief version (method ``model``) recording both stages' requests, approvals, estimates and reported
     usage, with the guards' findings; anything else is recorded, the validated first stage stays, and no version is
     saved.
3. Only the editors' explicit publication shows a version to users. Reading a story never prepares or sends anything.

Reported usage is kept with each stage's outcome, also when its reply is refused. A stage that failed is never sent
again in the same bytes. A failed stage 2 keeps its validated first stage: when a stage-2 input changes legitimately (a
revised stage-2 request contract or framework note), the next preview prepares a new stage-2 request from the same
foundations, approved on its own, and stage 1 is neither sent nor charged again. Changed material or context makes a
new stage 1. A request saved under an earlier contract is never sent (preview again): the single requests up to
brief-prompt-8 (``brief-<16 hex>``) and stages of an earlier version. Their files stay as they were and read as before.

Earlier single requests (kept for their records): brief-prompt-3 (2026-10-25) used a JSON output format instead of a
forced tool; brief-prompt-4 added the economic explanation; brief-prompt-7 typed every enum and removed nested unions
after brief-prompt-6 returned HTTP 400 with no message kept; brief-prompt-8 (brief_wire) removed every union, enum and
optional property. The provider rejected prompts 7 and 8 because "The compiled grammar is too large", which led to the
two stages (docs/news-brief-stages-2026-10-27.md (private; not in the public repository)). The application's content
contract for a brief written outside the application (an assisted batch's packet) is brief_contract's SYSTEM,
ECONOMICS_RULES and SCHEMA, re-exported here.

The key is read from the environment at send time and travels only in its header; a reply that carries it is not kept.
"""
import hashlib
import json
from pathlib import Path
import re

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import (analysis_flow, auth, brief_claims, brief_stages, brief_wire, econ_calc, econ_classification,
               econ_context, econ_framework, market_store, news_texts, newsroom_store as ns, story_briefs,
               story_economics)
from .accounts import AccountsRefused
from .brief_contract import ECONOMICS_RULES, ECONOMICS_SCHEMA, SCHEMA, SYSTEM  # noqa: F401  (re-exported)
from .draft_pilot import usage_cost
from .model_draft import DraftRefused, exposes, kept_outcome, observer, send_bytes, structured_reply
from .paid_drafts import key_problem
from .research_analysis import MODEL
from .research_requests import FORMAT_PROMPT_TOKENS

DRAFTING_VERSION = "brief-drafting-0.2"  # 0.2: two stages, each its own exact request and approval.
# 12: brief-evidence-4 then brief-explanation-4: a survey balance in every text. 13: brief-evidence-5 then
# brief-explanation-5: who says what, conditions, the procedural stage and a headline's bound (brief_claims). 14:
# brief-evidence-6 then brief-explanation-6 (or brief-summary-4): time and scope as the evidence states them, steps that
# are not a timeline, a limit kept with what it limits, and an alternative's support (econ-explanation-0.6). 15:
# brief-evidence-7: how long a flow lasts, and no calculation of a flow whose length is not established (econ-calc-0.5).
# 16: brief-evidence-8: a claim holder's name exactly as the material writes it, and plain text with no markup.
PROMPT_VERSION = "brief-prompt-16"
DRAFT_TEXT_CHARS = 20_000  # Of each publication's retained text in one request; the request says when it is cut.
EFFORT = "low"  # Set explicitly, for both stages.
THINKING = {"type": "adaptive"}
APPROVAL_FIELDS = ("request_sha256", "approve_paid_request", "estimated_max_usd")  # One attempt per request, ever.
DRAFT_ID = re.compile(r"brief-(?:s([12])-)?[0-9a-f]{16}")
NOT_ENABLED = ("Paid brief drafting is not enabled on this server; nothing was reserved or sent. It needs an explicit "
               "`python -m second_order serve --enable-paid-briefs` with the key in SECOND_ORDER_ANTHROPIC_API_KEY.")




def status(sender) -> dict:
    limits = {str(stage): tokens for stage, tokens in brief_stages.MAX_TOKENS.items()}
    if sender is None:
        return {"enabled": False, "detail": NOT_ENABLED, "model": MODEL, "max_tokens_by_stage": limits}
    problem = key_problem(sender.api_key())
    return {"enabled": problem is None, "detail": problem or (
        "Paid brief drafting is enabled: each of a draft's two requests is sent only after its own cost is shown and "
        "approved."), "model": MODEL, "max_tokens_by_stage": limits}


def framework_text(change: dict | None = None) -> str:
    """The framework notes as a request states them: general mechanisms, never evidence about the event, each with its
    limits and the subjects, forms of evidence and respondents it applies to. With the development's classified
    ``change`` (a second stage, from brief-prompt-11), only the notes whose subjects, forms and respondents all match
    (econ_classification), so a request never offers a mechanism its explanation may not name."""
    found = econ_framework.framework()
    notes = list(found["notes"].values()) if change is None else \
        econ_classification.applicable(found["notes"], change)
    if change is None:
        lines = ["Framework notes (general economic mechanisms, not evidence about this story; name one in a channel "
                 "only when it applies to the development's subject, form of evidence and respondents):"]
    else:
        what = econ_classification.describe(change)
        lines = [f"Framework notes listed as applying to this story's development ({what}): general economic "
                 "mechanisms, not evidence about this story. No other note applies; name only one of these, or none, "
                 "and keep within its limits."
                 if notes else f"Framework notes: none applies to this story's development ({what}), so a channel "
                 "names none."]
    for note in notes:
        whose = f"; respondents {', '.join(note['respondents'])}" if note["respondents"] else ""
        lines.append(f"- {note['id']} ({note['title']}; subjects {', '.join(note['applies_to'])}; evidence "
                     f"{', '.join(note['forms'])}{whose}): {note['mechanism']} Limits: {note['limits']}")
    return "\n".join(lines)


def context_text(bundle: dict | None) -> str:
    """The story's context bundle as a request states it, or that there is none."""
    if bundle is None:
        return "Context items: none (no context bundle was built for this story)."
    lines = [f"Context items (bundle {bundle['bundle_id']}; cite as context:<item ID>):"]
    for row in bundle["items"]:
        role = econ_context.ROLES.get(row.get("role"), "not stated")
        when = econ_context.TIMING[econ_context.item_timing(row, bundle)]
        why = f" Why it is here: {row['relevance']}" if row.get("relevance") else ""
        if row["kind"] == "publication":
            lines += [f"Item {row['item_id']}: publication from another story, {row['publisher']}, published "
                      f"{row['published'] or 'not stated'} ({row['text_basis'].replace('_', ' ')}): {row['title']}. "
                      f"Role: {role}. {when}{why}", row["text"]]
        else:
            lines += [f"Item {row['item_id']}: {row['kind']} from {row['source']} ({row['url']}), published "
                      f"{row['published']}, as of {row['as_of']}, retrieved {row.get('retrieved') or 'not stated'}. "
                      f"Role: {role}. {when}{why}", row["text"]]
    return "\n".join(lines)


def material_text(story: dict, material: dict, texts_folder: Path | None = None, bundle: dict | None = None,
                  framework: bool = True, change: dict | None = None) -> str:
    """The request's material: each report's headline and feed excerpt, plus its retained publication text
    (news_texts) where there is one, at most DRAFT_TEXT_CHARS of it, saying when it was cut; then the context bundle
    and, unless left out, the framework notes (only those applying to the classified ``change`` when it is given). A
    feed excerpt may hold evidence absent from the extracted text."""
    lines = [f"Story: {story['title']}", material["statement"], ""]
    for row in material["reports"]:
        lines += [f"Report ID: {row['entry_id']}", f"Publisher: {row['publisher']} ({row['role']})",
                  f"Published (as the feed states it): {row['published'] or 'not stated'}", f"Headline: {row['title']}"]
        text = row.get("text")
        held = news_texts.text_of(texts_folder, {"entry_id": row["entry_id"], "text_sha256": text["text_sha256"]}) \
            if text and texts_folder is not None else None
        if held is not None:
            if row["excerpt"]:
                lines.append(f"Excerpt: {row['excerpt']}")
            shown = held if len(held) <= DRAFT_TEXT_CHARS else held[:DRAFT_TEXT_CHARS].rsplit("\n\n", 1)[0] + (
                f"\n[The rest of this publication, {len(held) - DRAFT_TEXT_CHARS:,} or more characters, is not "
                "included in this request.]")
            lines += [f"Publication text ({text['state'].replace('_', ' ')}, retrieved {text['retrieved_at']}"
                      + (f"; {text['partial_reason']}" if text["partial_reason"] else "") + "):", shown, ""]
        else:
            lines += [f"Excerpt: {row['excerpt'] or '(none)'}", ""]
    lines.append(context_text(bundle))
    if framework:
        lines += ["", framework_text(change)]
    return "\n".join(lines)


# ---------------------------------------------------------------- the two requests

def _body(stage: int, user: str, brief_only: bool = False) -> bytes:
    shape = brief_wire.output_format(brief_stages.BRIEF_ONLY_SCHEMA) if brief_only else brief_stages.output_format(stage)
    system = brief_stages.BRIEF_ONLY_RULES if brief_only else brief_stages.system(stage)
    body = {"model": MODEL, "max_tokens": brief_stages.MAX_TOKENS[stage], "system": system,
            "thinking": dict(THINKING),
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema",
                                                           "schema": shape}},
            "messages": [{"role": "user", "content": user}]}
    return brief_stages.encoded(body)


def stage_1_bytes(story: dict, material: dict, texts_folder: Path | None = None, bundle: dict | None = None) -> bytes:
    """Stage 1's request: the material and the context items (the framework notes are the interpretation's)."""
    return _body(1, material_text(story, material, texts_folder, bundle, framework=False))


def stage_2_bytes(story: dict, material: dict, texts_folder: Path | None, bundle: dict | None, record: dict,
                  first_id: str) -> bytes:
    """Stage 2's request: the same material and context items, the framework notes, then the checked first stage."""
    brief_only = record["status"] == "insufficient_evidence"
    change = None if brief_only else record["checked"]["change"]
    return _body(2, material_text(story, material, texts_folder, bundle, framework=not brief_only,
                                  change=change) + "\n\n" + brief_stages.foundations_text(record, first_id),
                 brief_only=brief_only)


def planning_estimate(body: bytes, max_tokens: int) -> dict:
    """The planning estimate for these exact bytes (analysis_flow.cost_estimate; not a billing ceiling), counting
    FORMAT_PROMPT_TOKENS, assumed, for the system prompt the provider adds for a JSON output format (its size is not
    published)."""
    return analysis_flow.cost_estimate(body, max_tokens, (
        FORMAT_PROMPT_TOKENS, f"{FORMAT_PROMPT_TOKENS:,} assumed for the system prompt the provider adds for the JSON "
                              "output format (its size is not published)"))


def _usd(estimate: dict) -> float:
    return estimate["estimated_real_run_if_output_reaches_max_usd"]


def largest(material: dict) -> dict:
    """The largest first stage the limits allow (every list full, every text at its limit, in single-byte
    characters), from which stage 2's estimate is planned before stage 1 has replied. Never sent or saved."""
    word = lambda count: "x" * count  # noqa: E731
    ids = [row["entry_id"] for row in material["reports"]]
    figure = {"label": word(econ_calc.LIMITS["label"]), "value": -1234567.891, "decimals": 3,
              "unit": word(econ_calc.LIMITS["unit"]), "measure": "growth_rate",
              "period": word(econ_calc.LIMITS["period"]), "basis": "not_applicable",
              "seasonal": "not_seasonally_adjusted", "statistic": "other_summary", "stock_flow": "flow_annual_rate",
              "bound": "approximate", "price": True, "source": f"report:{ids[0]}",
              "quote": word(econ_calc.LIMITS["quote"]), "sign": "from_words",
              "sign_words": word(econ_calc.LIMITS["sign_words"]), "direction_check": "consistent",
              "vintage": {"label": word(econ_calc.LIMITS["vintage_label"])}}
    calculation = {"label": word(econ_calc.LIMITS["label"]), "value": -1234567.891, "decimals": 1,
                   "unit": "percentage points", "op": "difference", "bound": "approximate",
                   "formula": max(econ_calc.FORMULA.values(), key=len).format(a="f1", b="f2"),
                   "period": f"{word(econ_calc.LIMITS['period'])} against {word(econ_calc.LIMITS['period'])}"}
    claims = [{"id": f"k{index}", "holder": max(brief_claims.HOLDERS, key=len),
               "holder_name": word(brief_claims.LIMITS["name"]), "modality": max(brief_claims.MODALITIES, key=len),
               "quote": word(brief_claims.LIMITS["quote"]), "condition": word(brief_claims.LIMITS["condition"]),
               "source": f"report:{ids[0]}"} for index in range(1, story_briefs.COUNTS["facts"][1] + 1)]
    return {"status": "explained", "claims": claims,  # brief-evidence-5: every fact records a claim of full size.
            "facts": [{"text": word(story_briefs.LIMITS["item"]), "reports": ids, "claims": [row["id"]]}
                      for row in claims],
            "themes": [{"kind": "company", "name": word(story_briefs.LIMITS["theme_name"]),
                        "basis": word(story_briefs.LIMITS["theme_basis"])}] * story_briefs.COUNTS["themes"][1],
            "missing": [word(story_briefs.LIMITS["item"])] * story_briefs.COUNTS["missing"][1],
            "checked": {"change": {"text": word(story_economics.LIMITS["text"]),
                                   # The classification whose applicable framework notes make the longest request.
                                   **_longest(), "basis": [f"fact:{index}" for index in range(1, 9)]},
                        "figures": [{**figure, "id": f"f{index}"} for index in range(1, econ_calc.MAX_FIGURES + 1)],
                        "calculations": [{**calculation, "id": f"c{index}"}
                                         for index in range(1, econ_calc.MAX_CALCULATIONS + 1)]}}


def _longest() -> dict:
    """The stage, subject, form and respondents whose listed framework notes make the longest second request."""
    rows = [{"stage": max(econ_classification.FORM_STAGES[form], key=len), "instrument": subject, "form": form,
             "respondents": respondents}
            for subject in econ_framework.SUBJECTS for form in econ_framework.FORMS
            for respondents in (econ_framework.RESPONDENTS if form == "survey_answers" else (None,))]
    return max(rows, key=lambda row: (len(framework_text(row)), len(row["instrument"]), len(row["form"])))


# ---------------------------------------------------------------- saved requests and their state

def _folder(desk, draft_id: str) -> Path:
    return desk.newsroom.path.parent / "drafting" / draft_id


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _keep(path: Path, body: bytes) -> None:
    """Write a request's bytes once; the same bytes again are nothing new, and other bytes are refused."""
    try:
        with open(path, "xb") as file:
            file.write(body)
    except FileExistsError:
        if path.read_bytes() != body:
            raise AccountsRefused(409, "request_conflict", "A different request is saved under this ID; nothing was "
                                                           "sent.") from None


def _save(desk, stage: int, body: bytes, story: dict, bundle: dict | None, bound: dict | None = None,
          stage_version: str | None = None) -> str:
    """Save a stage's exact request once with its frozen inputs; its ID is its fingerprint."""
    digest = hashlib.sha256(body).hexdigest()
    draft_id = f"brief-s{stage}-{digest[:16]}"
    folder = _folder(desk, draft_id)
    folder.mkdir(parents=True, exist_ok=True)
    _keep(folder / "request.json", body)
    request = json.loads(body)
    try:
        market_store.write_exclusive(folder / "preview.json", {
            "drafting_version": DRAFTING_VERSION, "prompt_version": PROMPT_VERSION,
            "stages_version": brief_stages.VERSION, "stage": stage,
            "stage_version": stage_version or brief_stages.STAGE_VERSIONS[stage],
            "draft_id": draft_id, "story_id": story["story_id"],
            "material_sha256": story["material"]["material_sha256"], "material": story["material"],
            "request_sha256": digest, "model": MODEL, "max_tokens": brief_stages.MAX_TOKENS[stage], "effort": EFFORT,
            "thinking": THINKING, "system_sha256": hashlib.sha256(request["system"].encode("utf-8")).hexdigest(),
            "format_sha256": ns.sha256_of(request["output_config"]["format"]), "wire_version": brief_wire.VERSION,
            "analysis_version": story_economics.ANALYSIS_VERSION, "context": econ_context.summary(bundle),
            "framework": econ_framework.summary() if stage == 2 else None, "foundations": bound,
            "released_at": story["first_at"]})
    except FileExistsError:
        pass  # The same inputs made the same request before.
    return draft_id


def attempt_state(folder: Path) -> dict:
    """not_attempted, reserved, sending (started, no outcome recorded) or the recorded outcome."""
    outcome = _read(folder / "outcome.json")
    if outcome is not None:  # Outcomes recorded before 2026-10-27 hold no exchange or provider diagnostics.
        return {"state": outcome["outcome"], "detail": outcome["detail"], "version": outcome.get("version"),
                "at": outcome["finished_at"], "request_id": (outcome.get("exchange") or {}).get("request_id"),
                "provider_error": outcome.get("provider_error")}
    if (folder / "sent.json").exists():
        return {"state": "sending", "detail": ("The request was sent and no outcome is recorded; it is never sent "
                                               "again."), "version": None, "at": None}
    if (folder / "attempt.json").exists():
        return {"state": "reserved", "detail": "Reserved; nothing was sent.", "version": None, "at": None}
    return {"state": "not_attempted", "detail": None, "version": None, "at": None}


def superseded(record: dict) -> str | None:
    """Why a saved request may no longer be sent (it follows an earlier request contract), or None."""
    stage = record.get("stage")
    versions = {brief_stages.STAGE_VERSIONS.get(stage)} | ({brief_stages.BRIEF_ONLY_VERSION} if stage == 2 else set())
    if stage in (1, 2) and record.get("stage_version") in versions and \
            record.get("stages_version") == brief_stages.VERSION:
        return None
    current = brief_stages.STAGE_VERSIONS[stage] if stage in (1, 2) else PROMPT_VERSION
    return (f"it was saved under {record.get('stage_version') or record.get('prompt_version')}, an earlier request "
            f"contract than {current}")


def _foundations(desk, first_id: str) -> tuple[dict | None, str | None]:
    """(the validated first stage's foundations, their SHA-256), or (None, None) when that stage is not validated or
    its record does not match the fingerprint its outcome recorded."""
    folder = _folder(desk, first_id)
    outcome = _read(folder / "outcome.json")
    if not outcome or outcome.get("outcome") != "validated":
        return None, None
    try:
        data = (folder / "foundations.json").read_bytes()
    except OSError:
        return None, None
    digest = hashlib.sha256(data).hexdigest()
    if digest != outcome.get("foundations_sha256"):
        return None, None
    return json.loads(data.decode("utf-8")), digest


def _spent(folder: Path) -> dict | None:
    return usage_cost((_read(folder / "outcome.json") or {}).get("usage"))


# ---------------------------------------------------------------- the workflow

STOPPED = ("It is never sent again in the same bytes, and nothing more is prepared from it. Changed material or "
           "context, or a revised request contract, makes a new request, approved on its own.")


def _progress(first: dict, second: dict, record: dict | None) -> tuple[str, str, dict | None]:
    """(the workflow's state, what it means, the stage an approval now would send)."""
    one, two = first["attempt"]["state"], (second["attempt"] or {}).get("state")
    if one == "not_attempted":
        return "awaiting_stage_1", ("Stage 1 awaits its approval. Approving it sends stage 1 only; stage 2 is then "
                                    "prepared from its checked reply and needs its own approval."), first
    if one in ("reserved", "sending"):
        return "stopped", f"Stage 1 was reserved or sent and has no recorded outcome. {STOPPED}", None
    if one == "insufficient":
        return "complete", ("The model judged the material insufficient for a useful brief; that judgement was "
                            "recorded, and no second stage is needed."), None
    if one != "validated":
        return "stopped", f"Stage 1 ended as {one}. {STOPPED}", None
    if record is None:
        return "stopped", ("Stage 1's validated foundations cannot be read or do not match their recorded "
                           "fingerprint, so nothing is prepared from them."), None
    if two == "not_attempted":
        return "awaiting_stage_2", ("Stage 1 is validated and kept. Stage 2's exact request is prepared from it and "
                                    "awaits its own approval."), second
    if two in ("reserved", "sending"):
        return "stopped", ("Stage 2 was reserved or sent and has no recorded outcome; it is never sent again. The "
                           "validated stage 1 is kept."), None
    if two == "recorded":
        return "complete", (f"Both stages are done: version {second['attempt']['version']} was saved for the "
                            "editors and is not published."), None
    return "stopped", (f"Stage 2 ended as {two}; it is never sent again in the same bytes. The validated stage 1 is "
                       "kept: a revised stage-2 request contract or framework note makes a new stage-2 request from "
                       "it, approved on its own, without sending stage 1 again."), None


def workflow(desk, story: dict) -> dict:
    """The story's two-stage draft as it is now, saving its next exact request (once): what each stage does, its
    output limit and planning estimate, which stage has completed and what remains. Sends nothing."""
    material = story["material"]
    if not material["reports"]:
        raise AccountsRefused(409, "no_material", material["statement"])
    bundle = econ_context.current(desk, story)
    body = stage_1_bytes(story, material, desk.texts, bundle)
    first_id = _save(desk, 1, body, story, bundle)
    first_folder = _folder(desk, first_id)
    record, digest = _foundations(desk, first_id)
    first = {"stage": 1, "name": brief_stages.NAMES[1], "does": brief_stages.DOES[1],
             "stage_version": brief_stages.STAGE_VERSIONS[1], "draft_id": first_id,
             "request_sha256": hashlib.sha256(body).hexdigest(), "max_tokens": brief_stages.MAX_TOKENS[1],
             "estimate": planning_estimate(body, brief_stages.MAX_TOKENS[1]), "estimate_kind": "exact",
             "attempt": attempt_state(first_folder), "usage_cost": _spent(first_folder),
             "foundations": None if record is None else {
                 "status": record["status"], "sha256": digest, "facts": len(record["facts"]),
                 "figures": len(record["figures"]), "calculations": len(record["calculations"]),
                 "directions": brief_stages.directions(record)}}
    second = {"stage": 2, "name": brief_stages.NAMES[2], "does": brief_stages.DOES[2],
              "stage_version": brief_stages.STAGE_VERSIONS[2], "draft_id": None, "request_sha256": None,
              "max_tokens": brief_stages.MAX_TOKENS[2], "estimate": None, "estimate_kind": "not_needed",
              "attempt": None, "usage_cost": None, "bound_to": None}
    if record is not None:
        if record["status"] == "insufficient_evidence":
            second.update(stage_version=brief_stages.BRIEF_ONLY_VERSION, name="Brief from limited evidence",
                          does="Writes only the brief; retains the checked insufficient-evidence decision and reason.")
        second_body = stage_2_bytes(story, material, desk.texts, bundle, record, first_id)
        bound = {"draft_id": first_id, "request_sha256": first["request_sha256"], "foundations_sha256": digest,
                 "stage_version": (_read(first_folder / "preview.json") or {}).get("stage_version")}
        second_id = _save(desk, 2, second_body, story, bundle, bound, second["stage_version"])
        second_folder = _folder(desk, second_id)
        second.update(draft_id=second_id, request_sha256=hashlib.sha256(second_body).hexdigest(),
                      estimate=planning_estimate(second_body, brief_stages.MAX_TOKENS[2]), estimate_kind="exact",
                      attempt=attempt_state(second_folder), usage_cost=_spent(second_folder), bound_to=bound)
    elif first["attempt"]["state"] == "not_attempted":
        planned = stage_2_bytes(story, material, desk.texts, bundle, largest(material), first_id)
        second.update(estimate=planning_estimate(planned, brief_stages.MAX_TOKENS[2]), estimate_kind="planned")
    state, detail, upcoming = _progress(first, second, record)
    current = upcoming or (second if second["attempt"] else first)
    known = [row for row in (first, second) if row["estimate"] is not None]
    remaining = [row for row in known if row["attempt"] is None or row["attempt"]["state"] == "not_attempted"]
    spent = [row["usage_cost"]["usd"] for row in (first, second) if row["usage_cost"]]
    return {"drafting_version": DRAFTING_VERSION, "prompt_version": PROMPT_VERSION,
            "stages_version": brief_stages.VERSION, "story_id": story["story_id"],
            "material_sha256": material["material_sha256"], "material_statement": material["statement"],
            "state": state, "detail": detail, "next_stage": upcoming["stage"] if upcoming else None,
            "draft_id": current["draft_id"], "stage": current["stage"], "request_sha256": current["request_sha256"],
            "model": MODEL, "max_tokens": current["max_tokens"], "estimate": current["estimate"],
            "attempt": current["attempt"], "stages": [first, second],
            "combined": {
                "planning_estimate_usd": round(sum(_usd(row["estimate"]) for row in known), 4),
                "remaining_planning_estimate_usd": round(sum(_usd(row["estimate"]) for row in remaining), 4)
                if state.startswith("awaiting") else 0,
                "usage_cost_usd": round(sum(spent), 6) if spent else None,
                "statement": ("Planning estimates, not billing ceilings: each caps output at its max_tokens, but input "
                              "tokens are estimated and prices can change; the Console is authoritative. Approving a "
                              "stage sends that one exact request. Stage 2's estimate is planned from the largest "
                              "first stage the limits allow until stage 1 is validated; then its exact request is "
                              "shown for its own approval. Usage is as reported with each stage's reply.")},
            "sending": status(desk.drafting)}


def preview(desk, story: dict) -> dict:
    """The two-stage draft for this story's material now, with its next exact request saved (once). Sends nothing."""
    return workflow(desk, story)


# ---------------------------------------------------------------- approval and what came back

def _bundle(desk, story: dict, record: dict) -> dict | None:
    wanted = (record.get("context") or {}).get("bundle_id")
    return next((row for row in econ_context.bundles(desk, story["story_id"]) if row["bundle_id"] == wanted), None)


def _unchanged(desk, story: dict, record: dict) -> None:
    """Refuse, before anything is reserved, a request whose inputs are no longer those it was prepared from."""
    if story["material"]["material_sha256"] != record["material_sha256"]:
        raise AccountsRefused(409, "story_changed", "The story's material changed since this preview; preview again. "
                                                    "Nothing was reserved or sent.")
    bundle = econ_context.current(desk, story)
    if econ_context.summary(bundle) != record.get("context"):
        raise AccountsRefused(409, "inputs_changed", "The story's context bundle changed since this request was "
                                                     "prepared; preview again. Nothing was reserved or sent.")
    first_sha = hashlib.sha256(stage_1_bytes(story, story["material"], desk.texts, bundle)).hexdigest()
    prepared_sha = record["request_sha256"] if record["stage"] == 1 else (
        record.get("foundations") or {}).get("request_sha256")
    if first_sha != prepared_sha:
        raise AccountsRefused(409, "request_superseded", "This request's source packet no longer matches the current "
                                                        "preparation; preview again. Nothing was reserved or sent.")
    if record["stage"] != 2:
        return
    if econ_framework.summary() != record.get("framework"):
        raise AccountsRefused(409, "inputs_changed", "The framework notes changed since this request was prepared; "
                                                     "preview again. Nothing was reserved or sent.")
    bound = record.get("foundations") or {}
    found, digest = _foundations(desk, bound.get("draft_id", ""))
    first = _read(_folder(desk, bound.get("draft_id", "")) / "preview.json") or {}
    if found is None or digest != bound.get("foundations_sha256") or \
            first.get("stage_version") != brief_stages.STAGE_VERSIONS[1]:
        raise AccountsRefused(409, "inputs_changed", "The validated first stage this request was prepared from is not "
                                                     "as it was; preview again. Nothing was reserved or sent.")
    if (found["status"] == "insufficient_evidence") != (record.get("stage_version") == brief_stages.BRIEF_ONLY_VERSION):
        raise AccountsRefused(409, "request_superseded", "This request does not use the current contract for its "
                                                        "first-stage decision; preview again. Nothing was sent.")


def approve(desk, draft_id: str, form: dict, story_now, actor: str, clock) -> tuple[dict, bool]:
    """Send one previewed stage's exact request once after this explicit approval, and record what came back."""
    if not isinstance(draft_id, str) or DRAFT_ID.fullmatch(draft_id) is None:
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    folder = _folder(desk, draft_id)
    record = _read(folder / "preview.json")
    if record is None:
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    state = attempt_state(folder)
    if state["state"] != "not_attempted":
        return {"draft_id": draft_id, "stage": record.get("stage"), "attempt": state}, False
    reason = superseded(record)
    if reason:
        raise AccountsRefused(409, "request_superseded", f"This request cannot be sent: {reason}; nothing was "
                                                         "reserved or sent. Preview the story again.")
    if desk.drafting is None:
        raise AccountsRefused(409, "paid_drafting_disabled", NOT_ENABLED)
    key = desk.drafting.api_key()
    if key_problem(key):
        raise AccountsRefused(409, "paid_drafting_disabled", f"{key_problem(key)}; nothing was reserved or sent.")
    body = (folder / "request.json").read_bytes()
    estimate = _usd(planning_estimate(body, record["max_tokens"]))
    if form.get("approve_paid_request") is not True or form.get("request_sha256") != record["request_sha256"] or \
            hashlib.sha256(body).hexdigest() != record["request_sha256"] or form.get("estimated_max_usd") != estimate:
        raise AccountsRefused(409, "approval_mismatch", "The approval must repeat this request's SHA-256 and the "
                                                        "estimate shown, with approve_paid_request true. Nothing was "
                                                        "reserved or sent.")
    story = story_now(record["story_id"])
    _unchanged(desk, story, record)
    try:
        market_store.write_exclusive(folder / "attempt.json", {
            "draft_id": draft_id, "stage": record["stage"], "request_sha256": record["request_sha256"],
            "approved_by": actor, "approved_at": ns.stamp(clock()), "estimated_max_usd": estimate})
    except FileExistsError:
        return {"draft_id": draft_id, "stage": record["stage"], "attempt": attempt_state(folder)}, False
    sent_at = ns.stamp(clock())
    market_store.write_exclusive(folder / "sent.json", {"started_at": sent_at})
    outcome = {"outcome": "unknown", "detail": None, "finished_at": None, "usage": None, "version": None}
    seen, failure = {}, None
    try:
        with desk.drafting.client_factory(observer(seen, key)) as client:
            reply = send_bytes(client, body, key)
    except DraftRefused as exc:  # send_bytes says which: an error reply, a reply carrying the key, or no reply.
        text, failure = str(exc), exc
        outcome.update(outcome="provider_error" if "returned HTTP" in text else "invalid" if "credential" in text
                       else "unknown", detail=text)
        reply = None
    answered_at = ns.stamp(clock())
    if reply is not None:
        outcome.update(_recorded(desk, folder, story, record, reply, key, actor, estimate, clock))
    outcome["finished_at"] = ns.stamp(clock())
    outcome = kept_outcome(outcome, failure, seen, record["request_sha256"], sent_at, answered_at, key)
    market_store.write_exclusive(folder / "outcome.json", outcome)
    result = {"draft_id": draft_id, "stage": record["stage"], "attempt": attempt_state(folder)}
    if record["stage"] == 1 and outcome["outcome"] == "validated":
        try:  # Stage 2 is prepared from the checked reply (saved, not sent) for its own approval.
            prepared = workflow(desk, story_now(record["story_id"]))
            result["next"] = {name: prepared[name] for name in ("state", "detail", "draft_id", "stage",
                                                                "request_sha256", "estimate")}
        except AccountsRefused:
            result["next"] = None
    return result, True


def _recorded(desk, folder: Path, story: dict, record: dict, reply: bytes, key: str, actor: str, estimate: float,
              clock) -> dict:
    if exposes(reply, key):
        return {"outcome": "invalid", "detail": "The reply carried the credential; nothing of it was kept."}
    (folder / "response.json").write_bytes(reply)
    usage, response_id = None, None
    try:
        submitted, message = structured_reply(reply, record["model"])
        usage, response_id = message.get("usage"), message.get("id")
        basis = story_economics.evidence(story["material"], desk.texts, _bundle(desk, story, record),
                                         record.get("released_at"))
        if record["stage"] == 1:
            done = _first(desk, folder, story, record, submitted, basis, actor, clock)
        else:
            done = _second(desk, story, record, submitted, basis, actor, estimate, clock, usage, response_id)
    except (DraftRefused, AccountsRefused) as exc:
        return {"outcome": "invalid", "detail": str(exc), "usage": usage, "response_id": response_id}
    return {**done, "usage": usage, "response_id": response_id}


def _first(desk, folder: Path, story: dict, record: dict, submitted: object, basis: dict, actor: str, clock) -> dict:
    """Stage 1's reply: checked foundations kept for stage 2, or a judgement of insufficient material."""
    reply = brief_wire.decode(submitted, brief_stages.STAGE_1_SCHEMAS[record["stage_version"]])
    found = brief_stages.foundations(reply, story["material"], basis, record["stage_version"])
    if found["status"] == "insufficient_material":
        story_briefs.assess(desk.newsroom, story["story_id"], {
            "material_sha256": record["material_sha256"], "verdict": "insufficient", "reason": found["reason"],
            "idempotency_key": f"drafting-{record['draft_id']}"}, story["material"], actor, clock(), method="model")
        return {"outcome": "insufficient", "detail": ("The model judged the material insufficient for a useful brief; "
                                                      "that judgement was recorded, and no second stage is prepared "
                                                      "or sent.")}
    market_store.write_exclusive(folder / "foundations.json", {
        **found, "draft_id": record["draft_id"], "request_sha256": record["request_sha256"],
        "stage_version": record["stage_version"]})
    digest = hashlib.sha256((folder / "foundations.json").read_bytes()).hexdigest()
    detail = ("The evidence and figures passed the application's checks and are kept. Stage 2 is prepared from them "
              "for its own approval; nothing more was sent.") if found["status"] == "explained" else (
        "The facts passed the checks; the evidence was judged insufficient for an economic explanation, so stage 2 "
        "writes the brief only. It is prepared for its own approval; nothing more was sent.")
    return {"outcome": "validated", "detail": detail, "foundations_sha256": digest,
            "foundations_status": found["status"]}


def _stage_row(folder: Path, usage: object = None, response_id: str | None = None) -> dict:
    """What a version records of one stage: its request, approval, estimate and reported usage."""
    preview_record, attempt = _read(folder / "preview.json") or {}, _read(folder / "attempt.json") or {}
    outcome = _read(folder / "outcome.json") or {"usage": usage, "response_id": response_id}
    return {"stage": preview_record.get("stage"), "stage_version": preview_record.get("stage_version"),
            "draft_id": preview_record.get("draft_id"), "request_sha256": preview_record.get("request_sha256"),
            "max_tokens": preview_record.get("max_tokens"), "estimated_max_usd": attempt.get("estimated_max_usd"),
            "approved_by": attempt.get("approved_by"), "approved_at": attempt.get("approved_at"),
            "response_id": outcome.get("response_id"), "usage": outcome.get("usage"),
            "usage_cost": usage_cost(outcome.get("usage"))}


def _total(rows: list[dict]) -> tuple[dict | None, dict | None]:
    """(both stages' reported usage, its usage-derived cost), or None where a stage reported none."""
    usages = [row["usage"] for row in rows]
    if not all(isinstance(usage, dict) and type(usage.get("input_tokens")) is int and
               type(usage.get("output_tokens")) is int for usage in usages):
        return None, None
    total = {name: sum(usage[name] for usage in usages) for name in ("input_tokens", "output_tokens")}
    return total, usage_cost(total)


def _second(desk, story: dict, record: dict, submitted: object, basis: dict, actor: str, estimate: float, clock,
            usage: object, response_id: str | None) -> dict:
    """Stage 2's reply, assembled with the validated first stage into one unpublished version."""
    first_id = record["foundations"]["draft_id"]
    found, _ = _foundations(desk, first_id)
    if found is None:
        raise DraftRefused("The validated first stage could not be read as it was recorded")
    brief_only = record.get("stage_version") == brief_stages.BRIEF_ONLY_VERSION
    shape = brief_stages.BRIEF_ONLY_SCHEMA if brief_only else brief_stages.stage_2_schema(
        version=record["stage_version"])
    decoded = brief_wire.decode(submitted, shape)
    content = brief_stages.assemble_brief_only(found, decoded) if brief_only else brief_stages.assemble(
        found, decoded, record["stage_version"])
    rows = [_stage_row(_folder(desk, first_id)), _stage_row(_folder(desk, record["draft_id"]), usage, response_id)]
    total, cost = _total(rows)
    preparation = {"model": {"model": MODEL, "prompt_version": PROMPT_VERSION, "stages_version": brief_stages.VERSION,
                             "wire_version": brief_wire.VERSION, "draft_id": record["draft_id"],
                             "draft_ids": [row["draft_id"] for row in rows],
                             "request_sha256": record["request_sha256"], "response_id": response_id, "usage": total,
                             "stages": rows},
                   "cost": {"estimated_max_usd": round(sum(row["estimated_max_usd"] or 0 for row in rows), 4),
                            "usage_cost": cost, "approved_by": actor,
                            "stages": [{name: row[name] for name in ("stage", "estimated_max_usd", "usage_cost",
                                                                     "approved_by")} for row in rows]}}
    done, _ = story_briefs.add_version(
        desk.newsroom, story["story_id"],
        {"content": content, "based_on": story["brief"]["version"] if story.get("brief") else None,
         "idempotency_key": f"drafting-{record['draft_id']}"},
        story["material"], actor, clock(), method="model", preparation=preparation, basis=basis,
        findings=brief_stages.coherence(content, basis))
    explained = content["economics"]["status"] == "explained"
    return {"outcome": "recorded", "version": done["version"], "detail": (
        "A brief version with its economic explanation was saved for the editors to check; it is not published."
        if explained else "A brief version was saved for the editors to check, stating that the evidence is "
                          "insufficient for an economic explanation; it is not published.")}


def add_routes(app, desk, admin, call, write, story_now, clock) -> None:
    """The two drafting routes of the News desk (news_admin_api's helpers: the admin check, refusal mapping, the
    strict admin write and the story as it is now). The approval route serves either stage's request."""

    @app.post("/api/admin/news/stories/{story_id}/drafting")
    async def post_preview(story_id: str, request: Request):
        await write(request, (), "drafting preview")
        found = await run_in_threadpool(call, lambda: preview(desk, story_now(story_id)))
        return JSONResponse({"contract": auth.ADMIN_CONTRACT, "drafting": found})

    @app.post("/api/admin/news/drafting/{draft_id}/approval")
    async def post_approval(draft_id: str, request: Request):
        identity, form = await write(request, APPROVAL_FIELDS, "paid approval")
        done, sent = await run_in_threadpool(call, lambda: approve(desk, draft_id, form, story_now, identity.user_id,
                                                                   clock))
        return JSONResponse({"contract": auth.ADMIN_CONTRACT, "drafting": done, "sent": sent},
                            status_code=201 if sent else 200)

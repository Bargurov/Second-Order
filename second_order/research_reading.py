"""Reading an evidence-first research reply (see research_analysis): the output contract, the quote locator and the
classification of a received response, plus the local mock's Messages-API-shaped fixture.

Pure functions over bytes and text: nothing here reads or writes a record, sends anything or knows who asked. Moved
out of research_analysis unchanged; research_analysis re-exports every name.
"""
import json
import re
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .analysis_flow import FlowRefused
from .deeper_evidence import attribution
from .model_draft import SAFE_WORD, STOP_REASONS, DraftRefused, envelope, errors, strict_json
from .schema import FrozenModel
from .store import canonical

TOOL_NAME = "submit_research_analysis"

# The reply's bounds. Strict tool use cannot carry string lengths or item counts, so the prompt states them and the
# adapter enforces them after receipt.
MAX_ESTABLISHED = 10
MAX_QUOTES = 2
MIN_QUOTE = 8
MAX_QUOTE = 400
MAX_STATEMENT = 400
MAX_INTERPRETATION = 1_500
MAX_ITEM = 400
MAX_ITEMS = 6
MAX_SHOWN_TEXT = 4_000  # A declining reply's prose shown in the view; the full bytes stay in response.json.
NOT_PUBLISHERS = "not the publishers' own words"


Text = Annotated[str, Field(min_length=1, max_length=MAX_ITEM)]
Quote = Annotated[str, Field(min_length=MIN_QUOTE, max_length=MAX_QUOTE)]


class Established(FrozenModel):
    statement: Annotated[str, Field(min_length=1, max_length=MAX_STATEMENT)]
    basis: Literal["action", "data", "assessment", "forecast"]
    quotes: Annotated[tuple[Quote, ...], Field(min_length=1, max_length=MAX_QUOTES)]


class Interpretation(FrozenModel):
    kind: Literal["finding", "no_additional_finding"]
    text: Annotated[str, Field(min_length=1, max_length=MAX_INTERPRETATION)]
    based_on: Annotated[tuple[int, ...], Field(max_length=MAX_ESTABLISHED)]


class CompetingExplanation(FrozenModel):
    explanation: Text
    would_distinguish: Text


class Check(FrozenModel):
    check: Text
    counts_against_if: Text


class ResearchOutput(FrozenModel):
    """The only fields the model may supply."""
    established: Annotated[tuple[Established, ...], Field(min_length=1, max_length=MAX_ESTABLISHED)]
    interpretation: Interpretation
    assumptions: Annotated[tuple[Text, ...], Field(max_length=MAX_ITEMS)]
    competing_explanations: Annotated[tuple[CompetingExplanation, ...], Field(max_length=MAX_ITEMS)]
    missing_information: Annotated[tuple[Text, ...], Field(max_length=MAX_ITEMS)]
    tests: Annotated[tuple[Check, ...], Field(max_length=MAX_ITEMS)]


# ---------------------------------------------------------------- reading a response

def paragraphs(text: str) -> list[tuple[int, int]]:
    """The [start, end) spans of the blank-line-delimited paragraphs that hold text, in order."""
    spans, start = [], 0
    for gap in re.finditer(r"\n[ \t\r\f\v]*\n(?:[ \t\r\f\v]*\n)*", text):
        spans.append((start, gap.start()))
        start = gap.end()
    spans.append((start, len(text)))
    return [(begin, end) for begin, end in spans if text[begin:end].strip()]


TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                            "—": "-", "−": "-", " ": " "})


def _normalized(text: str) -> tuple[str, list[int]]:
    """Typographic quotes and dashes made plain and whitespace runs made one space, with each kept character's
    index in the original."""
    kept, where, space = [], [], False
    for index, char in enumerate(text.translate(TYPOGRAPHY)):
        if char.isspace():
            if not space:
                kept.append(" ")
                where.append(index)
            space = True
            continue
        kept.append(char)
        where.append(index)
        space = False
    return "".join(kept), where


def _every(needle: str, haystack: str) -> list[int]:
    """Every index where ``needle`` begins in ``haystack``, overlapping ones included."""
    found, start = [], haystack.find(needle) if needle else -1
    while start >= 0:
        found.append(start)
        start = haystack.find(needle, start + 1)
    return found


def _within(quote: str, source: str, spans: list[dict]) -> dict | None:
    """The first place a quote lies wholly inside one of ``spans`` (deeper_evidence): exactly, else after making
    quotes, dashes and whitespace plain. An occurrence in the framing, or one running from a passage into the next,
    does not count; ``occurrences`` counts the places inside a passage."""
    def inside(places: list[tuple[int, int]]) -> list[tuple[int, int, dict]]:
        return [(start, end, span) for start, end in places for span in spans
                if span["start"] <= start and end <= span["end"]]
    found, match = inside([(start, start + len(quote)) for start in _every(quote, source)]), "exact"
    if not found:
        plain, where = _normalized(source)
        wanted = _normalized(quote)[0].strip()
        found = inside([(where[at], where[at + len(wanted) - 1] + 1) for at in _every(wanted, plain)])
        match = "normalized"
    if not found:
        return None
    start, end, span = found[0]
    numbers = [number for number, (begin, finish) in enumerate(paragraphs(source), start=1)
               if begin < end and start < finish]
    return {"text": quote, "match": match, "start": start, "end": end, "paragraphs": numbers,
            "source_passage": source[start:end], "occurrences": len(found), "evidence": attribution(span)}


def locate(quote: str, source: str, spans: list[dict] | None = None) -> dict | None:
    """Where a quote is in the source: exactly, or after making quotes, dashes and whitespace plain. The located
    passage is the source's own wording; None when it is not there. With ``spans`` (a Go deeper source's publisher
    passages), only a place wholly inside one passage counts, and the quote says which report and part it is from."""
    if spans is not None:
        return _within(quote, source, spans)
    start = source.find(quote)
    if start >= 0:
        end, match, occurrences = start + len(quote), "exact", source.count(quote)
    else:
        plain, where = _normalized(source)
        wanted = _normalized(quote)[0].strip()
        found = plain.find(wanted) if wanted else -1
        if found < 0:
            return None
        start, end, match = where[found], where[found + len(wanted) - 1] + 1, "normalized"
        occurrences = plain.count(wanted)
    numbers = [number for number, (begin, finish) in enumerate(paragraphs(source), start=1)
               if begin < end and start < finish]
    return {"text": quote, "match": match, "start": start, "end": end, "paragraphs": numbers,
            "source_passage": source[start:end], "occurrences": occurrences}


def _thinking(block: dict) -> None:
    """A documented thinking or redacted_thinking block, with its fields of the documented types."""
    if block["type"] == "thinking":
        if not (isinstance(block.get("thinking"), str) and isinstance(block.get("signature"), str)):
            raise DraftRefused("A thinking block must carry string thinking and signature fields")
    elif not isinstance(block.get("data"), str):
        raise DraftRefused("A redacted_thinking block must carry a string data field")


def _submission(content: list) -> dict:
    """Exactly one call of the research tool; documented thinking blocks may accompany it, nothing else."""
    calls = []
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind in ("thinking", "redacted_thinking"):
            _thinking(block)
        elif kind == "tool_use":
            calls.append(block)
        else:
            shown = kind if isinstance(kind, str) and SAFE_WORD.fullmatch(kind) else "unrecognized"
            raise DraftRefused(f"Unexpected {shown} content block; only thinking blocks may accompany the research "
                               "tool call, and no analysis is read from prose")
    if len(calls) != 1:
        raise DraftRefused(f"The response must contain exactly one call of {TOOL_NAME}; it contains {len(calls)}")
    if calls[0].get("name") != TOOL_NAME or not isinstance(calls[0].get("input"), dict):
        raise DraftRefused(f"The tool call must be {TOOL_NAME} with an object input")
    return calls[0]["input"]


def _document(content: list) -> object:
    """research-prompt-2: the analysis as the response itself. Documented thinking blocks may accompany exactly one text
    block, which must be one JSON document and nothing else: no tool call, no prose around it, nothing extracted."""
    texts = []
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind in ("thinking", "redacted_thinking"):
            _thinking(block)
        elif kind == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        else:
            shown = kind if isinstance(kind, str) and SAFE_WORD.fullmatch(kind) else "unrecognized"
            raise DraftRefused(f"Unexpected {shown} content block; only thinking blocks may accompany the analysis, "
                               "which this contract asks for as the response itself")
    if len(texts) != 1:
        raise DraftRefused(f"The response must hold exactly one text block with the analysis; it holds {len(texts)}")
    try:
        return strict_json(texts[0].encode("utf-8"))
    except DraftRefused:
        raise DraftRefused("The reply's text is not one valid JSON document") from None


def _prose(content: list) -> str | None:
    """The text of a reply that submitted nothing. A tool call or an unknown block here breaks the contract."""
    texts = []
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif kind == "tool_use":
            raise DraftRefused("The response ended without submitting, yet it contains a tool call")
        elif kind not in ("thinking", "redacted_thinking"):
            raise DraftRefused("The response contains a content block this contract does not read")
    text = "\n\n".join(part.strip() for part in texts if part.strip())
    return text or None


def _resolved(output: ResearchOutput, source: str, spans: list[dict] | None = None) -> dict:
    """The analysis with every quote located in the captured text (with ``spans``, inside one publisher passage).
    Any quote that is not there refuses it all."""
    established = []
    for number, item in enumerate(output.established, start=1):
        if not item.statement.strip():
            raise DraftRefused(f"Established statement {number} is blank")
        quotes = []
        for position, quote in enumerate(item.quotes, start=1):
            long_enough = len(quote.strip()) >= MIN_QUOTE
            found = locate(quote, source, spans) if long_enough else None
            if found is None and spans is not None and long_enough and locate(quote, source) is not None:
                raise DraftRefused(f"Quote {position} of established statement {number} is {NOT_PUBLISHERS}: it is "
                                   "Second Order's framing, a label or a note, or it runs from one passage into "
                                   "another, so the analysis is not shown")
            if found is None:
                raise DraftRefused(f"Quote {position} of established statement {number} was not found in the "
                                   "captured text, so the analysis is not shown")
            quotes.append(found)
        established.append({"number": number, "statement": item.statement, "basis": item.basis, "quotes": quotes})
    reading = output.interpretation
    based_on = list(reading.based_on)
    if len(set(based_on)) != len(based_on) or any(not 1 <= number <= len(established) for number in based_on):
        raise DraftRefused("The interpretation's based_on must name distinct established statements by number")
    if reading.kind == "finding" and not based_on:
        raise DraftRefused("A finding must name the established statements it relies on")
    if not reading.text.strip():
        raise DraftRefused("The interpretation text is blank")
    return {"established": established,
            "interpretation": {"kind": reading.kind, "text": reading.text, "based_on": based_on},
            "assumptions": list(output.assumptions),
            "competing_explanations": [item.model_dump() for item in output.competing_explanations],
            "missing_information": list(output.missing_information),
            "tests": [item.model_dump() for item in output.tests]}


def classify(body: bytes, requested_model: str, source: str, spans: list[dict] | None = None,
             reply: str = "tool") -> dict:
    """The recorded outcome of a received response, with the analysis or the prose it carries. Never raises.
    ``spans``: the publisher passages a Go deeper source's request binds (deeper_evidence); None for any other
    source, whose whole captured text is evidence. ``reply``: how the request asked for the analysis, "tool" (a strict
    tool's input, research-prompt-1) or "format" (the response itself in the JSON output format, research-prompt-2)."""
    def outcome(name: str, problem: str | None = None, analysis: dict | None = None, text: str | None = None) -> dict:
        return {"outcome": name, "problem": problem, "analysis": analysis, "model_text": text}
    if reply not in ("tool", "format"):
        return outcome("refused", "No analysis: the request names a reply format this reader does not know")
    try:
        message = envelope(strict_json(body))
    except DraftRefused as exc:
        return outcome("refused", str(exc))
    if message["model"] != requested_model:
        return outcome("refused", f"The provider answered with model {message['model']!r}, not the requested "
                                  f"{requested_model!r}")
    stop = message["stop_reason"]
    if stop == "refusal" or (stop == "end_turn" and reply == "tool"):
        try:
            text = _prose(message["content"])
        except DraftRefused as exc:
            return outcome("refused", str(exc))
        reason = "the model declined" if stop == "refusal" else "the model ended without calling the research tool"
        category = (message.get("stop_details") or {}).get("category")
        if stop == "refusal" and isinstance(category, str) and SAFE_WORD.fullmatch(category):
            reason += f" (category {category})"
        shown = text if text is None or len(text) <= MAX_SHOWN_TEXT else text[:MAX_SHOWN_TEXT] + " [shortened]"
        return outcome("declined", f"No analysis: {reason}", text=shown)
    if stop in ("max_tokens", "model_context_window_exceeded", "pause_turn"):
        return outcome("incomplete", f"No analysis: {STOP_REASONS[stop]}")
    if reply == "format" and stop == "tool_use":
        return outcome("refused", "No analysis: the reply called a tool, but this contract offers no tool")
    if stop != ("end_turn" if reply == "format" else "tool_use"):
        return outcome("refused", "No analysis: an unexpected stop reason")
    try:
        submitted = _document(message["content"]) if reply == "format" else _submission(message["content"])
        parsed = ResearchOutput.model_validate_json(json.dumps(submitted), strict=True)
        analysis = _resolved(parsed, source, spans)
    except DraftRefused as exc:
        return outcome("refused", str(exc))
    except ValidationError as exc:
        return outcome("refused", f"The analysis failed strict validation: {errors(exc)}")
    kind = "analysis" if analysis["interpretation"]["kind"] == "finding" else "no additional finding"
    return outcome(kind, analysis=analysis)


# ---------------------------------------------------------------- the local mock

def _mock_output(source: str, outcome: str, spans: list[dict] | None = None) -> dict:
    """The fixture's reply: it quotes the source's paragraphs, or with ``spans`` its publisher passages."""
    places = [(begin, end) for begin, end in paragraphs(source)] if spans is None else \
        [(span["start"], span["end"]) for span in spans]
    pieces = [source[begin:end].strip() for begin, end in places]
    passages = [text for text in pieces if len(text) >= 40] or [text for text in pieces if len(text) >= MIN_QUOTE]
    if not passages:
        raise FlowRefused(409, "The captured text has no passage long enough for the mock fixture to quote; nothing "
                               "was reserved")
    bases = ("action", "assessment", "forecast")
    established = [{"statement": (f"Mock statement {number} for workflow testing: the captured text contains this "
                                  "passage. The basis label is synthetic, not a reading of the source."),
                    "basis": bases[(number - 1) % len(bases)], "quotes": [passage[:MAX_QUOTE].rstrip()]}
                   for number, passage in enumerate(passages[:3], start=1)]
    finding = outcome == "analysis"
    return {
        "established": established,
        "interpretation": {"kind": "finding" if finding else "no_additional_finding",
                           "text": ("Mock interpretation for workflow testing; it is not a research finding."
                                    if finding else "Mock result: the available evidence supports no additional "
                                                    "finding. Written by a local fixture, not by a model."),
                           "based_on": [1] if finding else []},
        "assumptions": ["Mock assumption: written by a local fixture to exercise the review form."],
        "competing_explanations": [{"explanation": "Mock competing explanation.",
                                    "would_distinguish": "Mock: what would tell the two readings apart."}],
        "missing_information": ["Mock: information the fixture cannot know."],
        "tests": [{"check": "Mock check a researcher could make.",
                   "counts_against_if": "Mock: what would count against the interpretation."}],
    }


def mock_response(request: dict, source: str, outcome: str, request_hash: str,
                  spans: list[dict] | None = None) -> bytes:
    """A Messages-API-shaped local fixture. No transport exists here. ``spans``: a Go deeper source's publisher
    passages, which it then quotes instead of the source's paragraphs. A request that offers no tool (research-prompt-2)
    gets the analysis as the response's text, and a decline as a refusal: that contract has no prose decline."""
    identity = request_hash[:20]
    if "tools" not in request:
        if outcome == "declined":
            content = [{"type": "text", "text": ("Mock refusal for workflow testing: this local response submits no "
                                                 "analysis. No provider was contacted.")}]
            stop_reason = "refusal"
        else:
            content = [{"type": "thinking", "thinking": "", "signature": f"sig-mock-{identity}"},
                       {"type": "text", "text": canonical(_mock_output(source, outcome, spans))}]
            stop_reason = "end_turn"
    elif outcome == "declined":
        content = [{"type": "text", "text": ("Mock decline for workflow testing: this local response submits no "
                                             "analysis. No provider was contacted.")}]
        stop_reason = "end_turn"
    else:
        content = [{"type": "thinking", "thinking": "", "signature": f"sig-mock-{identity}"},
                   {"type": "tool_use", "id": f"toolu_mock_{identity}", "name": TOOL_NAME,
                    "input": _mock_output(source, outcome, spans)}]
        stop_reason = "tool_use"
    response = {"id": f"msg_mock_{identity}", "type": "message", "role": "assistant", "model": request["model"],
                "content": content, "stop_reason": stop_reason, "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0}}
    return canonical(response).encode("utf-8")

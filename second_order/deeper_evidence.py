"""Where a Go deeper source's publisher passages are (deeper-evidence-0.1).

A Go deeper source (story_deeper) holds the reports' own words (each headline, feed excerpt and retained publication
text) between Second Order's framing: what the source is, the story's title, what is left out, the labels of each
report (Publisher, Published, Address, Headline, Excerpt, Credit) and the note on a shortened text. Only the
publishers' words are evidence. Go deeper records, with the source and once, where each of them sits: a span of
[start, end) code-point offsets into the saved source text, the SHA-256 of the span's UTF-8 bytes, the report's
number, entry ID and publisher, and the part (headline, excerpt or text). The record names the SHA-256 of the whole
source text too, so it fits one saved text only. A research request binds it (research_analysis), and every quote of a
reply must lie wholly inside one span (research_reading.locate).

Pure functions: nothing here reads or writes a file.
"""
import hashlib
import re

EVIDENCE_VERSION = "deeper-evidence-0.1"
PARTS = ("headline", "excerpt", "text")
SPAN_FIELDS = ("start", "end", "sha256", "report", "entry_id", "publisher", "part")
RECORD_FIELDS = ("evidence_version", "source_sha256", "spans")
SHA256 = re.compile(r"[0-9a-f]{64}")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def span(start: int, words: str, number: int, row: dict, part: str) -> dict:
    """The record of one publisher passage, ``words``, beginning at ``start``."""
    return {"start": start, "end": start + len(words), "sha256": sha256(words), "report": number,
            "entry_id": row["entry_id"], "publisher": row["publisher"], "part": part}


def record(text: str, spans: list[dict]) -> dict:
    return {"evidence_version": EVIDENCE_VERSION, "source_sha256": sha256(text), "spans": spans}


def attribution(found: dict) -> dict:
    """What a located quote says about where it came from: the report's number, its publisher and the part."""
    return {key: found[key] for key in ("report", "publisher", "part")}


def problem(evidence: object, text: str) -> str | None:
    """Why ``evidence`` is not a record of publisher passages in ``text``, or None when it is: the exact fields, the
    whole text's SHA-256, each span inside the text, in order and apart, with its recorded hash."""
    if not isinstance(evidence, dict) or set(evidence) != set(RECORD_FIELDS):
        return f"the evidence record does not hold exactly {', '.join(RECORD_FIELDS)}"
    if evidence["evidence_version"] != EVIDENCE_VERSION:
        return f"the evidence record is not {EVIDENCE_VERSION}"
    if evidence["source_sha256"] != sha256(text):
        return "the evidence record names another source text"
    spans = evidence["spans"]
    if not isinstance(spans, list) or not spans:
        return "the evidence record names no publisher passage"
    previous = 0
    for number, found in enumerate(spans, start=1):
        if not isinstance(found, dict) or set(found) != set(SPAN_FIELDS):
            return f"passage {number} does not hold exactly {', '.join(SPAN_FIELDS)}"
        if found["part"] not in PARTS:
            return f"passage {number} names an unknown part"
        if not all(isinstance(found[key], str) and found[key] for key in ("entry_id", "publisher")) or \
                not isinstance(found["sha256"], str) or not SHA256.fullmatch(found["sha256"]):
            return f"passage {number} names no report entry, publisher or hash"
        bounds = (found["start"], found["end"], found["report"])
        if any(isinstance(value, bool) or not isinstance(value, int) for value in bounds) or found["report"] < 1:
            return f"passage {number}'s offsets or report number are not whole numbers"
        if not 0 <= found["start"] < found["end"] <= len(text):
            return f"passage {number} lies outside the source text"
        if found["start"] < previous:
            return f"passage {number} is out of order or overlaps the one before"
        previous = found["end"]
    for number, found in enumerate(spans, start=1):  # Once every passage has its place.
        if sha256(text[found["start"]:found["end"]]) != found["sha256"]:
            return f"passage {number} no longer has its recorded hash"
    return None

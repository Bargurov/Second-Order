"""Go deeper: from a shared story to the user's own analysis of its permitted material (story-deeper-0.2).

The story page offers it; nothing runs on that click. ``preview`` (a read) shows exactly what would be used: the
story's material (story_briefs.material: the reports whose publishers allow analysis, with each publication's text where
this server retained it (news_texts), otherwise the headline and excerpt as the feed gave them) and the source text it
becomes, with what is left out and why. The shared brief is never part of it: its implications are the editors' or an
AI's reading, not evidence, so a deeper analysis reads the reports alone. ``start`` is the person's
explicit action: it saves that text as a source the user owns, through the existing source path and its limits
(counted once as a new source), records where it came from (data/story-deeper/<source ID>.json, write-once, beside
and never inside the capture), and prepares the analysis at the chosen Effort through the existing path (counted once
as a preparation; reopening is free). Nothing is quoted, sent or charged: the analysis page then shows the credit
quote, and only the person's approval of it runs anything, under the existing credits, daily limit, ownership and
single-attempt rules.

The source names, once, where its publishers' own words are (deeper-evidence-0.1): each report's headline, feed
excerpt and retained publication text, by report and publisher. The rest (what it is, the story's title, what is left
out, each report's labels and any note on a shortened text) is Second Order's framing, and the analysis may quote none
of it: the record is kept in the origin record (story-deeper-link-0.2) and every research request of the source binds
it (research_analysis). A source saved by story-deeper-0.1, without that record, keeps its analyses and results but is
not analysed again; Go deeper makes a new source of the same material instead of reusing it.

Repeating the action with the same material reuses the user's source (and the prepared analysis, if that Effort was
prepared): one source per user, story and material. Another account's source is never reused or shown. The shared brief
and the newsroom are only read.
"""
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading

from . import accounts as acc, deeper_evidence, entitlements, market_store, news_texts, news_views
from . import research_analysis as ra
from . import user_research
from .model_draft import MAX_SOURCE_CHARS
from .newsroom_store import resolve_story
from .accounts import AccountsRefused, Identity
from .analysis_flow import FlowRefused, strict_object

DEEPER_VERSION = "story-deeper-0.2"
LINK_VERSION = "story-deeper-link-0.2"
ROOT = Path(__file__).resolve().parent.parent
DEEPER_DIR = ROOT / "data" / "story-deeper"  # Runtime records; data/ is ignored by git.
MAX_HEADLINE = 1_500
STATEMENT = ("This source was assembled from a shared story's material by Go deeper. It holds the reports' headlines "
             "and feed excerpts as the feeds gave them, not the publications.")
TEXT_STATEMENT = ("This source was assembled from a shared story's material by Go deeper. It holds the text of each "
                  "publication this server retrieved from the publisher's own page, and the headline and feed excerpt "
                  "of any other report, never the shared brief.")
ROOM = 400  # Characters kept free under the source limit for the closing lines.
EVIDENCE_LINE = ("Only the reports' own words can be quoted as evidence: each headline, feed excerpt and publication "
                 "text below. These opening lines, the labels of each report (such as \"Publisher:\" or \"Headline:\") "
                 "and any note in square brackets are Second Order's, not a publisher's, and a quote from them is not "
                 "accepted.")
_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
_GUARD = threading.Lock()


def reference(user_id: str, story_id: str, material_sha256: str) -> str:
    """This user's reference for this material: two accounts' sources of one story are two sources, never one capture."""
    return "deeper-" + hashlib.sha256(f"{user_id}|{story_id}|{material_sha256}".encode("utf-8")).hexdigest()[:12]


def _texts(texts_folder: Path | None, rows: list[dict]) -> dict[str, str]:
    """The retained text of each report that has one, only when its bytes still match the material's SHA-256."""
    found = {}
    for row in rows:
        text = row.get("text")
        if text and texts_folder is not None:
            held = news_texts.text_of(texts_folder, {"entry_id": row["entry_id"], "text_sha256": text["text_sha256"]})
            if held is not None:
                found[row["entry_id"]] = held
    return found


def assemble(story: dict, material: dict, user_id: str, texts_folder: Path | None = None) -> tuple[str, dict]:
    """The source a deeper analysis reads, and where its publishers' words are in it (deeper-evidence-0.1). What it
    is first, then each report: its publication's text where this server retained it, otherwise its headline and
    excerpt as its feed gave them. Within the source limit; a text that does not fit is shortened at a paragraph and
    says so. Every line is Second Order's framing except the words after a report's "Headline:" and "Excerpt:" labels
    and its publication text: those are the spans the evidence record names."""
    rows = material["reports"]
    left = sorted({row["publisher"] for row in material["not_used"]})
    texts = _texts(texts_folder, rows)
    plural = lambda number, word: f"{number} {word}{'s' if number != 1 else ''}"  # noqa: E731
    if texts:
        what = (f"What this is: the text of {plural(len(texts), 'publication')}, as this server retrieved "
                f"{'it' if len(texts) == 1 else 'them'} from the publisher's own page"
                + (f", and the headline and feed excerpt of {plural(len(rows) - len(texts), 'other report')}, whose "
                   "publications were not read." if len(texts) < len(rows) else "."))
    else:
        what = (f"What this is: the headline{'s' if len(rows) != 1 else ''} and feed excerpt"
                f"{'s' if len(rows) != 1 else ''} of {plural(len(rows), 'report')}, as the publishers' feeds gave "
                "them. A headline or excerpt is discovery metadata, not the publication: the full publications were "
                "not read.")
    # Each line: framing text, or (label, the publisher's words, report number, report, part), or (report number,
    # report) where a publication's text goes once the room left for it is known.
    lines: list = [f"Material for a deeper analysis of a news story, assembled by Second Order ({DEEPER_VERSION}; "
                   f"reference {reference(user_id, story['story_id'], material['material_sha256'])}).",
                   f"Story: {story['title']}", what,
                   "The shared brief of this story is not included: an analysis reads the reports themselves.",
                   EVIDENCE_LINE]
    if left:
        lines.append(f"Left out: reports by {', '.join(left)}, whose terms grant no use for analysis.")
    for number, row in enumerate(rows, start=1):
        lines += ["", f"Report {number} of {len(rows)}", f"Publisher: {row['publisher']}",
                  f"Published (as the feed states it): {row['published'] or 'not stated'}", f"Address: {row['link']}",
                  ("Headline: ", row["title"], number, row, "headline")]
        if row["entry_id"] in texts:
            text = row["text"]
            partial = f"part of it: {text['partial_reason']}; " if text["partial_reason"] else ""
            lines += [f"Text of the publication ({partial}retrieved {text['retrieved_at'][:16].replace('T', ' ')} UTC "
                      f"from {text['url']}):", (number, row)]
        elif row["excerpt"]:
            lines.append(("Excerpt: ", row["excerpt"], number, row, "excerpt"))
        else:
            lines.append("Excerpt: (the feed gave no excerpt)")
        if row["attribution"]:
            lines.append(f"Credit: {row['attribution']}")
    slot = lambda line: isinstance(line, tuple) and len(line) == 2  # noqa: E731
    fixed = [line if isinstance(line, str) else line[0] + line[1] for line in lines if not slot(line)]
    room = MAX_SOURCE_CHARS - (len("\n".join(fixed)) + len(lines) + 1) - ROOM  # Each text slot adds a line break.
    shown: list = []
    for line in lines:
        if not slot(line):
            shown.append(line)
            continue
        number, row = line
        held = texts[row["entry_id"]]
        if len(held) > room:
            cut = held[:max(0, room)].rsplit("\n\n", 1)[0] if room > 0 else ""
            note = (f"[Shortened here to fit the source limit: {len(held) - len(cut):,} more characters of this "
                    "publication are not included.]")
            shown += [("", cut, number, row, "text"), note]
            held = f"{cut}\n{note}"
        else:
            shown.append(("", held, number, row, "text"))
        room = max(0, room - len(held))
    parts, spans, offset = [], [], 0
    for line in shown:
        if isinstance(line, str):
            parts.append(line)
        else:
            label, words, number, row, part = line
            if words.strip():
                spans.append(deeper_evidence.span(offset + len(label), words, number, row, part))
            parts.append(label + words)
        offset += len(parts[-1]) + 1  # The line and its line break.
    text = "\n".join(parts) + "\n"
    return text, deeper_evidence.record(text, spans)


def source_text(story: dict, material: dict, user_id: str, texts_folder: Path | None = None) -> str:
    """The source a deeper analysis reads (assemble), without the record of its publishers' passages."""
    return assemble(story, material, user_id, texts_folder)[0]


def _form(story: dict, user_id: str, texts_folder: Path | None = None) -> tuple[dict, dict]:
    material = story["material"]
    stated = sorted((row for row in material["reports"] if row["published_utc"]),
                    key=lambda row: (row["published_utc"], row["entry_id"]))
    earliest = stated[0]
    text, evidence = assemble(story, material, user_id, texts_folder)
    return {"headline": story["title"][:MAX_HEADLINE], "source_url": earliest["link"],
            "published_at": earliest["published_utc"], "source_text": text}, evidence


def source_form(story: dict, user_id: str, texts_folder: Path | None = None) -> dict:
    """The source form a deeper analysis saves: the story's headline, the earliest report with a stated time (its
    address and that time) and the material's text."""
    return _form(story, user_id, texts_folder)[0]


def _story(desk: news_views.Desk, story_id: str, now: datetime) -> tuple[dict, str]:
    found = news_views.world(desk, now)
    target = resolve_story(found["folded"], story_id) if isinstance(story_id, str) else None
    if target not in found["stories"]:
        raise AccountsRefused(404, "not_found", news_views.NOT_FOUND)
    return found["stories"][target], target


def _links(desk: news_views.Desk, identity: Identity, story_id: str, material_sha256: str,
           context: user_research.UserResearch) -> str | None:
    """The user's source already made from this story's material, if one is recorded with its publishers' passages
    (story-deeper-link-0.2) and is still theirs. A story-deeper-0.1 source is not reused: it records no passages."""
    if not desk.deeper.is_dir():
        return None
    for path in sorted(desk.deeper.glob("*.json")):
        try:
            record = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("link_version") != LINK_VERSION:
            continue
        if record.get("user_id") == identity.user_id and record.get("story_id") == story_id and \
                record.get("material_sha256") == material_sha256 and \
                acc.owner_of(context.accounts, "capture", record.get("capture_id")) == identity.user_id:
            return record["capture_id"]
    return None


def _analyses(context: user_research.UserResearch, identity: Identity, source_id: str | None) -> list[dict]:
    if source_id is None:
        return []
    detail = user_research.source_detail(context, identity, source_id)
    return [{"analysis_id": row["analysis_id"], "effort": row["effort"]} for row in detail["analyses"]]


def preview(desk: news_views.Desk, context: user_research.UserResearch, identity: Identity, story_id: str,
            now: datetime) -> dict:
    """What Go deeper would use and save, and what this user already made from it. Reads only."""
    story, target = _story(desk, story_id, now)
    state = news_views.deeper_state(story)
    material = story["material"]
    form = source_form(story, identity.user_id, desk.texts) if state["available"] else None
    existing = _links(desk, identity, target, material["material_sha256"], context) if state["available"] else None
    return {"deeper_version": DEEPER_VERSION, "story_id": target, "title": story["title"], **state,
            "material": {key: material[key] for key in ("coverage", "statement", "reports", "not_used")},
            "material_sha256": material["material_sha256"],
            "source": None if form is None else {**{key: form[key] for key in ("headline", "source_url",
                                                                              "published_at")},
                                                 "characters": len(form["source_text"]), "text": form["source_text"]},
            "existing": None if existing is None else {"source_id": existing,
                                                       "analyses": _analyses(context, identity, existing)},
            "statement": ("Going deeper saves this material as your own source and prepares an analysis of it: one new "
                          "source and one prepared analysis of today's allowance, and no credits. The analysis runs "
                          "only after you approve its credit quote. The shared brief is not changed.")}


def start(desk: news_views.Desk, context: user_research.UserResearch, identity: Identity, story_id: str,
          body: bytes, now: datetime) -> tuple[dict, bool]:
    """The explicit action: save the material as the user's source (or reuse it) and prepare the analysis at the
    chosen Effort (or reopen it). ``body``: exactly material_sha256 and effort. Nothing is quoted, sent or charged."""
    try:
        form = strict_object(body, ("material_sha256", "effort"), "deeper analysis")
    except FlowRefused:
        raise AccountsRefused(422, "invalid_request", "Going deeper names exactly material_sha256 and effort.") \
            from None
    story, target = _story(desk, story_id, now)
    state = news_views.deeper_state(story)
    if not state["available"]:
        raise AccountsRefused(409, "deeper_unavailable", state["reason"])
    material = story["material"]
    if form["material_sha256"] != material["material_sha256"]:
        raise AccountsRefused(409, "story_changed", "This story's material changed since the page was read. Nothing "
                                                    "was saved; read it again to see what would be used now.")
    efforts = entitlements.offered_efforts(entitlements.current_policy(context.accounts), ra.MODEL)
    if form["effort"] not in efforts:
        raise AccountsRefused(409, "unsupported_effort", "This Effort is not offered. Choose one of the listed options.",
                              efforts=user_research.effort_options(efforts))
    with _GUARD:
        lock = _LOCKS[identity.user_id]
    with lock:  # One Go deeper at a time per account: a double press makes one source.
        source_id = _links(desk, identity, target, material["material_sha256"], context)
        new_source = source_id is None
        if new_source:
            built, evidence = _form(story, identity.user_id, desk.texts)
            saved = user_research.add_source(context, identity, json.dumps(built, ensure_ascii=False).encode("utf-8"))
            source_id = saved["source"]["source_id"]
            if deeper_evidence.problem(evidence, saved["source"]["text"]) is not None:  # Saved exactly as built.
                raise AccountsRefused(500, "internal_error", "The source was saved, but where its publishers' words "
                                                             "are could not be recorded. Nothing was prepared.")
            brief = story["brief"]
            market_store.write_exclusive(desk.deeper / f"{source_id}.json", {
                "link_version": LINK_VERSION, "capture_id": source_id, "user_id": identity.user_id,
                "story_id": target, "material_sha256": material["material_sha256"],
                "brief": None if brief is None else {"version": brief["version"],
                                                     "content_sha256": brief["content_sha256"]},
                "reports": [{"entry_id": row["entry_id"], "version_sha256": row["version_sha256"],
                             "text_sha256": (row.get("text") or {}).get("text_sha256")}
                            for row in material["reports"]],
                "evidence": evidence, "recorded_at": now.isoformat(timespec="seconds"),
                "statement": TEXT_STATEMENT if any(row.get("text") for row in material["reports"]) else STATEMENT})
    prepared, created = user_research.prepare(context, identity, json.dumps(
        {"source_id": source_id, "effort": form["effort"]}).encode("utf-8"))
    source = user_research.source_detail(context, identity, source_id)["source"]
    return {"deeper_version": DEEPER_VERSION, "story_id": target, "source": {key: source[key] for key in (
        "source_id", "headline", "source_url", "published_at", "captured_at", "characters")},
            "analysis": prepared["analysis"], "created_source": new_source, "created_analysis": created}, \
        new_source or created

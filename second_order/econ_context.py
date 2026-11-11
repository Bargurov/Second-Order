"""Context bundles for economic explanations (econ-context-0.2): additional evidence an operator gathers explicitly.

A story's own material is its first evidence. When an explanation needs a comparison, a measurement definition or more
evidence, an operator builds a bundle for the story (``news context build``). Nothing is fetched: every item comes from
this server's records, the methodology library or the operator's file.

- **Other stories' material**: the earlier developments of the story's ongoing topics, the previous release of the
  same series (another story with a report from the same feed under the same title, first reported earlier), or
  stories the operator names with the reason. Their headlines, excerpts and retained texts are used under their
  publishers' own terms.
- **Methodology** (econ_methodology.json): passages that define how a series is measured, kept per series (a feed and
  its release titles), each with the document it was read from, its dates and why it matters for reading the
  series. A later release of the same series offers the same passages, dated as read from the earlier release.
- **The operator's items**: passages of a publication (event evidence, or a comparison) and expectations benchmarks,
  each with its source, address, dates, retrieval date, quoted text, terms and the reason it is relevant.

0.2: every item has a ``role`` (evidence on this development, a comparison, methodology or a benchmark) and a
``relevance`` (why it is in the bundle), and its ``timing`` against the story's first report: published before it,
the same day, or after it. An item published after the story was first reported is retrospective context, labelled
as such wherever it is shown, and never the basis of what the development was (story_economics' guard). The bundle
records the story's first report and its own cutoff (when it was gathered). Bundles built under 0.1 are read as
they were saved.

A bundle is written once (data/newsroom/context/<story ID>/<bundle ID>.json); its ID is made from the story's material
and the items, so building the same bundle again finds it. A brief version records the bundle it was prepared with; a
bundle built for the current material after an explanation was prepared makes that explanation outdated
(news_explanations), so the next batch prepares it again with the newer context.
"""
from datetime import date, datetime
from functools import lru_cache
import json
from pathlib import Path
import re

from . import market_store, news_texts, newsroom_store as ns
from .accounts import AccountsRefused

CONTEXT_VERSION = "econ-context-0.2"
VERSIONS = ("econ-context-0.1", CONTEXT_VERSION)
METHODOLOGY_VERSION = "econ-methodology-0.1"
METHODOLOGY = Path(__file__).with_name("econ_methodology.json")
KINDS = ("publication", "observation", "expectation", "methodology")
ROLES = {"event_evidence": "Evidence on this development", "comparison": "An earlier comparable release or development",
         "methodology": "How the measure is defined or compiled", "benchmark": "An expectations benchmark"}
ROLES_OF = {"publication": ("event_evidence", "comparison"), "observation": ("event_evidence", "comparison"),
            "expectation": ("benchmark",), "methodology": ("methodology",)}
TIMING = {"before": "Published before this story was first reported.",
          "same_day": "Published on the day this story was first reported.",
          "after": ("Published after this story was first reported: later context, not what was known when it "
                    "was reported."),
          "unknown": "Its publication date is not known."}
MAX_ITEMS = 12
TOPIC_HISTORY = 3  # Earlier developments of each topic, most recent first.
TEXT_CHARS = 6_000  # Of a publication's retained text in a bundle; the item says when it is cut.
SUPPLIED_FIELDS = {"kind", "role", "source", "url", "published", "as_of", "retrieved", "text", "terms", "relevance"}
LIMITS = {"source": 120, "text": 2_000, "terms": 300, "relevance": 300}
BUNDLE_ID = re.compile(r"ctx-[0-9a-f]{16}")


def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_request", detail)


def _folder(desk, story_id: str) -> Path:
    return desk.newsroom.path.parent / "context" / story_id


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def timing(published: object, first_at: str | None) -> str:
    """When an item was published against the story's first report, by date."""
    day = str(published or "")[:10]
    first = str(first_at or "")[:10]
    try:
        date.fromisoformat(day)
        date.fromisoformat(first)
    except ValueError:
        return "unknown"
    return "before" if day < first else "same_day" if day == first else "after"


def _text(value: object, field: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > LIMITS[field]:
        raise _refuse(f"{where}'s {field} is text of 1 to {LIMITS[field]} characters.")
    return value.strip()


def _iso_date(value: object, label: str) -> str:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise _refuse(f"{label} is a date (YYYY-MM-DD).")


# ---------------------------------------------------------------- the methodology library

@lru_cache(maxsize=1)
def methodology() -> dict:
    """The methodology library, checked: each series has its feed, release titles, document, dates, terms and
    passages, each passage with what it defines and why it matters."""
    value = json.loads(METHODOLOGY.read_text(encoding="utf-8"))
    if value.get("methodology_version") != METHODOLOGY_VERSION or not isinstance(value.get("series"), list):
        raise ValueError(f"{METHODOLOGY.name} is not {METHODOLOGY_VERSION}.")
    seen = set()
    for series in value["series"]:
        if set(series) != {"series_id", "source", "titles", "publisher", "document", "url", "published",
                           "retrieved", "terms", "checked_against", "passages"} or series["series_id"] in seen:
            raise ValueError(f"{METHODOLOGY.name}: a series has exactly its fields and a unique ID.")
        seen.add(series["series_id"])
        if not series["url"].startswith("https://") or not series["titles"] or not series["passages"]:
            raise ValueError(f"{series['series_id']}: an https document, release titles and passages.")
        for name in ("published", "retrieved"):
            _iso_date(series[name], f"{series['series_id']}'s {name}")
        for passage in series["passages"]:
            if set(passage) != {"text", "defines", "relevance"} or not passage["defines"]:
                raise ValueError(f"{series['series_id']}: each passage has its text, what it defines and why.")
    return value


def methodology_for(story: dict) -> list[dict]:
    """The library's series whose feed and release title match one of the story's usable reports (not words)."""
    keys = {(row["source"], row["title"]) for row in story["reports"] if row["material"] == "permitted"}
    return [series for series in methodology()["series"]
            if any((series["source"], title) in keys for title in series["titles"])]


def _methodology_items(story: dict) -> list[dict]:
    items = []
    for series in methodology_for(story):
        for passage in series["passages"]:
            items.append({"kind": "methodology", "role": "methodology", "source": f"{series['publisher']}, "
                          f"{series['document']}", "publisher": series["publisher"], "url": series["url"],
                          "published": series["published"], "as_of": series["published"],
                          "retrieved": series["retrieved"], "text": passage["text"], "terms": series["terms"],
                          "defines": passage["defines"], "series_id": series["series_id"],
                          "relevance": passage["relevance"]})
    return items


# ---------------------------------------------------------------- other stories

def _publication(desk, story: dict, row: dict, item_id: str, role: str, relevance: str) -> dict:
    text = row.get("text")
    held = news_texts.text_of(desk.texts, {"entry_id": row["entry_id"], "text_sha256": text["text_sha256"]}) \
        if text and desk.texts is not None else None
    if held is not None:
        shown, basis = held[:TEXT_CHARS], text["state"]
        if len(held) > TEXT_CHARS:
            shown += f"\n[The rest of this publication, {len(held) - TEXT_CHARS:,} characters, is not in the bundle.]"
    else:
        shown, basis = "\n".join(part for part in (row["title"], row["excerpt"]) if part), "headline_and_excerpt"
    return {"item_id": item_id, "kind": "publication", "role": role, "relevance": relevance,
            "story_id": story["story_id"], "story_title": story["title"], "entry_id": row["entry_id"],
            "publisher": row["publisher"], "title": row["title"], "link": row["link"],
            "published": row["published_utc"] or row["published"], "reported_at": story["first_at"], "text": shown,
            "text_basis": basis, "attribution": row["attribution"]}


def earlier_release(found: dict, story: dict) -> dict | None:
    """The previous release of the same series: the latest other story first reported before this one with a usable
    report from the same feed under the same title (a monthly release keeps its title)."""
    keys = {(row["source"], row["title"]) for row in story["reports"] if row["material"] == "permitted"}
    earlier = [other for other in found["stories"].values()
               if other["story_id"] != story["story_id"] and other["first_at"] < story["first_at"] and
               any((row["source"], row["title"]) in keys for row in other["reports"] if row["material"] == "permitted")]
    return max(earlier, key=lambda other: (other["first_at"], other["story_id"])) if earlier else None


def _topic_history(found: dict, story: dict) -> list[tuple[str, str]]:
    rows = []
    for topic in story["topics"]:
        timeline = found["topics"][topic["topic_id"]]["timeline"]
        for other in list(reversed(timeline[:timeline.index(story["story_id"])]))[:TOPIC_HISTORY]:
            rows.append((other, f"An earlier development of the topic “{topic['title']}”, first reported "
                                f"{found['stories'][other]['first_at'][:10]}."))
    return rows


def candidates(desk, found: dict, story_id: str) -> dict:
    """What a bundle for the story could hold, and why, before anything is recorded (reads only)."""
    story = found["stories"].get(ns.resolve_story(found["folded"], story_id) or "")
    if story is None:
        raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
    rows = [{"option": "--methodology", "role": "methodology", "series_id": series["series_id"],
             "document": series["document"], "published": series["published"],
             "timing": timing(series["published"], story["first_at"]), "passages": len(series["passages"]),
             "relevance": f"The methodology of {series['publisher']}'s series, read from {series['document']}."}
            for series in methodology_for(story)]
    previous = earlier_release(found, story)
    if previous is not None:
        rows.append({"option": "--earlier-release", "role": "comparison", "story_id": previous["story_id"],
                     "title": previous["title"], "published": previous["first_at"],
                     "timing": timing(previous["first_at"], story["first_at"]),
                     "relevance": "The previous release of the same series."})
    for other, reason in _topic_history(found, story):
        rows.append({"option": "--topic-history", "role": "comparison", "story_id": other,
                     "title": found["stories"][other]["title"], "published": found["stories"][other]["first_at"],
                     "timing": timing(found["stories"][other]["first_at"], story["first_at"]), "relevance": reason})
    return {"context_version": CONTEXT_VERSION, "story_id": story["story_id"], "first_reported": story["first_at"],
            "candidates": rows, "statement": (
                "Matched by structure (the same feed and release title, a methodology series, a topic's timeline), "
                "never by shared words alone. Nothing is recorded until a bundle is built.")}


# ---------------------------------------------------------------- the operator's items

def _supplied(rows: object, actor: str) -> list[dict]:
    """The operator's own items, each with its role, source, dates, terms and why it is relevant."""
    if not isinstance(rows, list):
        raise _refuse("A supplied file is {items: [...]}.")
    items = []
    for index, row in enumerate(rows, start=1):
        where = f"Supplied item {index}"
        if not isinstance(row, dict) or set(row) != SUPPLIED_FIELDS or row["kind"] not in KINDS[1:]:
            raise _refuse(f"{where} has exactly: {', '.join(sorted(SUPPLIED_FIELDS))}; its kind is observation, "
                          "expectation or methodology.")
        if row["role"] not in ROLES_OF[row["kind"]]:
            raise _refuse(f"{where}: a {row['kind']}'s role is {' or '.join(ROLES_OF[row['kind']])}.")
        if not isinstance(row["url"], str) or not row["url"].startswith("https://"):
            raise _refuse(f"{where}'s url is an https address.")
        items.append({"kind": row["kind"], "role": row["role"], "source": _text(row["source"], "source", where),
                      "url": row["url"], "published": _iso_date(row["published"], f"{where}'s published"),
                      "as_of": _iso_date(row["as_of"], f"{where}'s as_of"),
                      "retrieved": _iso_date(row["retrieved"], f"{where}'s retrieved"),
                      "text": _text(row["text"], "text", where), "terms": _text(row["terms"], "terms", where),
                      "relevance": _text(row["relevance"], "relevance", where), "supplied_by": actor})
    return items


# ---------------------------------------------------------------- building and reading bundles

def build(desk, found: dict, story_id: str, now: datetime, actor: str,
          with_stories: list[tuple[str, str]] | None = None, topic_history: bool = False, supplied: object = None,
          use_methodology: bool = False, use_earlier_release: bool = False) -> tuple[dict, bool]:
    """Gather and record a bundle for ``story_id`` (once). ``with_stories``: (story ID, why it is relevant) pairs."""
    story = found["stories"].get(ns.resolve_story(found["folded"], story_id) or "")
    if story is None:
        raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
    others: list[tuple[str, str, str]] = []
    if use_earlier_release:
        previous = earlier_release(found, story)
        if previous is None:
            raise AccountsRefused(409, "no_earlier_release", "No earlier story has a usable report from the same feed "
                                                             "under the same title.")
        others.append((previous["story_id"], "comparison", "The previous release of the same series, first reported "
                                                          f"{previous['first_at'][:10]}."))
    if topic_history:
        others += [(other, "comparison", reason) for other, reason in _topic_history(found, story)]
    for name, reason in with_stories or []:
        target = ns.resolve_story(found["folded"], name)
        if target not in found["stories"]:
            raise AccountsRefused(404, "not_found", f"{name} is not a current story.")
        others.append((target, "comparison", _text(reason, "relevance", f"The reason for {name}")))
    items: list[dict] = []
    for other, role, reason in {row[0]: row for row in others}.values():
        if other == story["story_id"]:
            continue
        for row in found["stories"][other]["material"]["reports"]:  # Only what its publishers allow to be used.
            items.append(_publication(desk, found["stories"][other], row, f"p{len(items) + 1}", role, reason))
    own = _methodology_items(story) if use_methodology else []
    if use_methodology and not own:
        raise AccountsRefused(409, "no_methodology", "The methodology library holds no series for this story's "
                                                     "reports.")
    own += _supplied(supplied.get("items") if isinstance(supplied, dict) else [], actor) if supplied else []
    count = dict.fromkeys(KINDS[1:], 0)
    for row in own:
        count[row["kind"]] += 1
        items.append({"item_id": f"{row['kind'][0]}{count[row['kind']]}", **row})
    if not items:
        raise AccountsRefused(409, "nothing_to_bundle", "No permitted material of another story, no methodology and "
                                                        "no supplied item: nothing would be in the bundle.")
    if len(items) > MAX_ITEMS:
        raise _refuse(f"A bundle holds at most {MAX_ITEMS} items; this one would hold {len(items)}.")
    for row in items:  # A feed's own date format may not parse: then the time the other story was first reported.
        row["timing"] = timing(row.get("published"), story["first_at"])
        if row["timing"] == "unknown" and row.get("reported_at"):
            row["timing"] = timing(row["reported_at"], story["first_at"])
    body = {"context_version": CONTEXT_VERSION, "story_id": story["story_id"],
            "material_sha256": story["material"]["material_sha256"], "story_first_reported": story["first_at"],
            "items": items}
    bundle_id = "ctx-" + ns.sha256_of(body)[:16]
    folder = _folder(desk, story["story_id"])
    existing = _read(folder / f"{bundle_id}.json")
    if existing is not None:
        return existing, False
    record = {**body, "bundle_id": bundle_id, "bundle_sha256": ns.sha256_of(body), "built_at": ns.stamp(now),
              "cutoff": ns.stamp(now), "built_by": actor, "statement": (
                  "Gathered explicitly from this server's saved records, the methodology library and the operator's "
                  "own items; nothing was fetched. Each item keeps its source, its dates, the terms under which it is "
                  "used, its role and why it is relevant; an item published after the story was first reported is "
                  "later context.")}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        market_store.write_exclusive(folder / f"{bundle_id}.json", record)
    except FileExistsError:
        return _read(folder / f"{bundle_id}.json"), False
    return record, True


def bundles(desk, story_id: str) -> list[dict]:
    """Every bundle built for a story, oldest first (reads only)."""
    folder = _folder(desk, story_id)
    rows = [_read(path) for path in sorted(folder.glob("ctx-*.json"))] if folder.is_dir() else []
    return sorted((row for row in rows if row and BUNDLE_ID.fullmatch(row.get("bundle_id", ""))),
                  key=lambda row: (row["built_at"], row["bundle_id"]))


def current(desk, story: dict) -> dict | None:
    """The latest bundle built for the story's material as it is now, or None."""
    rows = [row for row in bundles(desk, story["story_id"])
            if row["material_sha256"] == story["material"]["material_sha256"]]
    return rows[-1] if rows else None


def item_timing(row: dict, bundle: dict) -> str:
    """An item's timing as recorded (0.2), or as its dates show against the story's first report (0.1)."""
    return row.get("timing") or timing(row.get("published"), bundle.get("story_first_reported"))


def evidence(bundle: dict | None) -> dict[str, dict]:
    """Each item as evidence a figure may quote: ``context:<item ID>`` -> its text, source, time, role and timing."""
    if bundle is None:
        return {}
    return {f"context:{row['item_id']}": {
        "text": row["text"], "publisher": row.get("publisher") or row.get("source"),
        "published": row.get("published"), "kind": row["kind"], "as_of": row.get("as_of"),
        "role": row.get("role"), "timing": row.get("timing")}
        for row in bundle["items"]}


def summary(bundle: dict | None) -> dict | None:
    """What a brief version records of the bundle it was prepared with."""
    if bundle is None:
        return None
    return {"bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
            "context_version": bundle["context_version"], "items": len(bundle["items"]),
            "built_at": bundle["built_at"]}

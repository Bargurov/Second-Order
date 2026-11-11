"""Related research (related-research-0.1): navigation from one event to content already in the case library.

This is research navigation, apart from Related Cases' strict policy matching (related_rules): it never compares
mechanisms, predicts or establishes cause. An event is an Event Inbox entry (its current version, or its latest archived
one) or a saved capture. Its inputs are its own stored text and metadata only: title or headline, feed excerpt or
supplied source text, its address and the date its feed or operator states. Saved headline classifications are not
used. Nothing is computed ahead of time, stored, fetched, classified or sent: a read selects links from local records.

Three relationships, strongest first; each target appears once, under the strongest one that holds:
- same_event (coverage of this event): the event's address names one document (EVENT_ADDRESSES: an article or
  release page, its query kept exactly; never a landing page or a page reused for every release), exactly one case
  cites that address, every held event that names it states the same date, and that date is the case's publication
  date. Headlines never identify an event, and a conflicting or missing date prevents this label; a case at the event's
  address that cannot be confirmed this way is not offered under a weaker label either. It describes library coverage
  of the same release, not an analogy or a second source.
- release_family (same named release family): the event's own title and its address's host and path place it in a
  family (FAMILIES), as the case's source title and address place the case. A shared publisher is not a family. The
  link is the latest case of that family published on or before the event's date, with the document type and dates
  stated; minutes and a statement are different documents of one family.
- topic (related research topic): the event's own text names a topic of the small vocabulary (TOPICS: every group of
  terms must be found), and the topic's case states the same terms in its own title or summary (checked when the
  vocabulary is read). It is a shared subject, not the same mechanism.
Family and topic links go only to cases published on or before the event's stated date (later cases are counted and
not suggested in this version), so an undated event gets neither. Case writeups were prepared after the fact; each link
says so. Cases shown as related in the event's stored historical match are not repeated here.
"""
from datetime import date
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import (case_library, event_context, event_inbox, event_intake, event_links, event_overview, inbox_imports,
               related_cases, related_matches)
from .market_context import ContextRefused

NAVIGATION_VERSION = "related-research-0.2"  # 0.2: the trade-and-environment topic.
VIEW_VERSION = "related-research-view-0.1"
MAX_LINKS = 4
RELATIONS = {"same_event": "Coverage of this event", "release_family": "Same release family",
             "topic": "Related research topic"}
ORDER = tuple(RELATIONS)
MONTHS = {name: number for number, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                                                       "Oct", "Nov", "Dec"), start=1)}
_EDGE_BEFORE, _EDGE_AFTER = r"(?<![^\W_])", r"(?![^\W_])"

# Addresses that name one document. Anything else (a landing page, an index, the current-release page BLS reuses every
# month) cannot identify an event. (host, path, query: None when the address must have none.)
EVENT_ADDRESSES = (
    ("www.eia.gov", r"/todayinenergy/detail\.php", r"id=\d+"),
    ("www.federalreserve.gov", r"/newsevents/pressreleases/[a-z]+\d{8}[a-z]\.htm", None),
    ("www.federalreserve.gov", r"/releases/(?:g17|h8)/\d{8}/", None),
    ("www.bls.gov", r"/news\.release/archives/[a-z]+_\d{8}\.htm", None),
    ("www.bis.gov", r"/press-release/[a-z0-9]+(?:-[a-z0-9]+)*", None),
    ("home.treasury.gov", r"/news/press-releases/[a-z]{2}\d+", None),
    ("www.wto.org", r"/english/news_e/news\d{2}_e/[a-z0-9_]+_e\.htm", None),
)

# Named release families: an event's own title (or a case's source title) names the document, and its address's host
# and path confirm the publisher's release series. A title alone, or a publisher alone, places nothing in a family.
FAMILIES = {
    "fomc": {"label": "FOMC communications", "host": "www.federalreserve.gov", "path": "/newsevents/pressreleases/",
             "documents": (("statement", "an FOMC statement", r"FOMC statement"),
                           ("minutes", "FOMC meeting minutes", r"Minutes of the Federal Open Market Committee"),
                           ("projections", "FOMC economic projections", r"economic projections .*FOMC meeting"))},
    "employment-situation": {"label": "The Employment Situation (BLS)", "host": "www.bls.gov", "path": "/news.release/",
                             "documents": (("release", "an Employment Situation release", r"The Employment Situation"),)},
    "cpi": {"label": "Consumer Price Index (BLS)", "host": "www.bls.gov", "path": "/news.release/",
            "documents": (("release", "a CPI release", r"Consumer Price Index"),)},
    "g17": {"label": "Industrial Production and Capacity Utilization (G.17)", "host": "www.federalreserve.gov",
            "path": "/releases/g17/",
            "documents": (("release", "a G.17 release", r"Industrial Production and Capacity Utilization"),)},
    "h8": {"label": "Assets and Liabilities of Commercial Banks (H.8)", "host": "www.federalreserve.gov",
           "path": "/releases/h8/",
           "documents": (("release", "an H.8 release", r"Assets and Liabilities of Commercial Banks"),)},
}

# Research topics: concrete subjects of existing cases. Every group must be found in the event's own text; each topic's
# case must state every group in its own title or summary (checked when read), so a topic stays tied to the case. A
# topic may state a difference every link to it carries (for example, that the forums differ).
TOPICS = {
    "natural-gas-market": {
        "label": "US natural gas prices, production and storage", "case": "eia-tie-2026-09-25",
        "groups": ((r"natural gas", r"Henry Hub"), (r"prices?", r"production", r"storage")),
        "case_basis": "the case reads EIA's report of the summer Henry Hub average price, record natural gas "
                      "production and storage going into winter"},
    "oil-gas-producers": {
        "label": "Who produces US crude oil and natural gas", "case": "eia-tie-2026-09-22",
        "groups": ((r"crude oil", r"natural gas", r"oil and gas"), (r"production", r"producers?", r"operators?",
                                                                     r"output")),
        "case_basis": "the case reads EIA's report of which companies produce US crude oil and natural gas, by basin, "
                      "including the Permian and the Haynesville"},
    "ev-electricity": {
        "label": "Electricity used by electric vehicles", "case": "eia-tie-2026-09-30",
        "groups": ((r"electric vehicles?",), (r"electricity", r"charging", r"kilowatthours?")),
        "case_basis": "the case reads EIA's estimate of the electricity used by light-duty electric vehicles"},
    "trade-environment-wto": {
        "label": "Trade and environment work at the WTO", "case": "wto-2026-09-28",
        "groups": ((r"environmental sustainability", r"trade and environment", r"climate measures?", r"plastics"),
                   (r"co-sponsors", r"Committee on Trade and Environment", r"structured discussions", r"dialogue")),
        "case_basis": "the case reads the WTO Secretariat's note on the Committee on Trade and Environment meeting of "
                      "28-29 September 2026, which the co-sponsors of member-led initiatives, including the plastics "
                      "dialogue and the structured discussions on environmental sustainability, briefed",
        "difference": "Different forums: the case covers a meeting of the Committee on Trade and Environment, a WTO "
                      "committee; initiatives led by co-sponsoring members are separate forums, and the case reports "
                      "only that their co-sponsors briefed the committee."},
}
_GROUPS = {slug: [[re.compile(_EDGE_BEFORE + term + _EDGE_AFTER, re.IGNORECASE) for term in group]
                  for group in topic["groups"]] for slug, topic in TOPICS.items()}
FIELD_LABELS = {"title": "the entry's title", "excerpt": "the feed excerpt", "headline": "the capture's headline",
                "source_text": "the source text supplied with the capture"}
NOT_ANALOGY = "A shared subject, not the same mechanism and not a comparison of outcomes."
SOURCE_CHECK_LABELS = {"verified": "Checked on this machine against the retained copy",
                       "absent": "Retained copy not on this machine",
                       "different": "The file on this machine is not the recorded copy"}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")


class ResearchRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _invalid(problem: str) -> ResearchRefused:
    return ResearchRefused(500, f"The related-research vocabulary is invalid ({problem}); nothing is served")


# ---------------------------------------------------------------- addresses, dates, families, topics

def event_address(url: str | None) -> str | None:
    """The address in normal form when it names one document (EVENT_ADDRESSES), else None. Nothing is resolved."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme != "https" or parts.fragment or parts.username or parts.password or parts.port:
        return None
    for listed, path, query in EVENT_ADDRESSES:
        if host == listed and re.fullmatch(path, parts.path) and \
                (not parts.query if query is None else re.fullmatch(query, parts.query) is not None):
            return f"https://{host}{parts.path}" + (f"?{parts.query}" if parts.query else "")
    return None


def stated_date(raw: str | None) -> date | None:
    """The calendar date a feed timestamp or a supplied time states, as written (no zone conversion), or None."""
    if not isinstance(raw, str):
        return None
    try:
        iso = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", raw)
        if iso:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        rfc = re.search(r"\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4})\b", raw)
        return date(int(rfc[3]), MONTHS[rfc[2]], int(rfc[1])) if rfc else None
    except ValueError:
        return None


def family_of(title: str | None, url: str | None) -> tuple[str, str] | None:
    """(family, document) when the title names a family's document and the address is on its host and path."""
    if not isinstance(title, str) or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    for slug, family in FAMILIES.items():
        if parts.scheme != "https" or host != family["host"] or not parts.path.startswith(family["path"]):
            continue
        for document, _, pattern in family["documents"]:
            if re.search(_EDGE_BEFORE + pattern + _EDGE_AFTER, title, re.IGNORECASE):
                return slug, document
    return None


def document_label(family: str, document: str) -> str:
    return next(label for slug, label, _ in FAMILIES[family]["documents"] if slug == document)


def topic_terms(slug: str, fields: dict[str, str | None]) -> list[dict] | None:
    """What the fields state of each group of a topic (first term found per group), or None if any group is missing."""
    found = []
    for group in _GROUPS[slug]:
        hit = next(({"term": match.group(0), "field": field} for field, text in fields.items() if text
                    for pattern in group for match in [pattern.search(text)] if match), None)
        if hit is None:
            return None
        found.append(hit)
    return found


# ---------------------------------------------------------------- targets

def _library_cases(library: Path) -> list[dict] | None:
    """The case library's cases, or None when it is not installed here (an invalid library is refused)."""
    try:
        return case_library.load_library(library)["cases"]
    except case_library.LibraryRefused as exc:
        if exc.status == 503:
            return None
        raise


def _targets(library: Path, historical: Path, sources: Path) -> list[dict]:
    """Every case a link can name: the case library's release cases and the historical cases, with dates and status."""
    found = []
    installed = _library_cases(library)
    for case in installed or []:
        day, _ = case_library.publication(case["source"])
        found.append({"collection": "library", "id": case["id"], "title": case["title"], "category": case["category"],
                      "date": day, "date_as_stated": case["source"]["published_as_stated"],
                      "address": event_address(case["source"]["url"]), "url": case["source"]["url"],
                      "family": family_of(case["source"]["title"], case["source"]["url"]),
                      "reference_period": case["source"]["reference_period"], "href": f"/library/{case['id']}",
                      "text": f"{case['title']} {case['summary']}",
                      "status": {"kind": "editorial", "prepared_on": case["provenance"]["prepared_on"],
                                 "labels": ["Editorial case", "AI-assisted", "Not human-reviewed",
                                            "Not research evidence"],
                                 "source": f"Source read online on {case['source']['retrieved_on']}; no copy retained.",
                                 "source_check": None}})
    try:
        loaded = related_cases.load(historical)
    except related_cases.RelatedRefused:
        loaded = {"cases": []}  # The historical section reports its own problem; release cases are still offered.
    for case in loaded["cases"]:
        check = related_cases.source_check(case, sources)
        found.append({"collection": "historical", "id": case["id"], "title": case["title"], "category": case["topic"],
                      "date": related_cases.announced(case), "date_as_stated": case["source"]["date_as_stated"],
                      "address": event_address(case["source"]["url"]), "url": case["source"]["url"],
                      "family": None, "reference_period": None, "href": f"/library/historical/{case['id']}",
                      "text": f"{case['title']} {case['summary']['text']}",
                      "status": {"kind": "historical", "prepared_on": case["provenance"]["prepared_on"],
                                 "labels": ["Historical case", "Facts quoted from a retained page",
                                            "Interpretation AI-assisted", "Not human-reviewed"],
                                 "source": SOURCE_CHECK_LABELS[check["state"]] + ".",
                                 "source_check": check["state"]}})
    by_id = {(target["collection"], target["id"]): target for target in found}
    for slug, topic in TOPICS.items() if installed is not None else ():
        target = by_id.get(("library", topic["case"]))
        if target is None:
            raise _invalid(f"topic {slug} names {topic['case']}, which the case library does not hold")
        if topic_terms(slug, {"case": target["text"]}) is None:
            raise _invalid(f"the case {topic['case']} does not state every term group of topic {slug}")
    return found


# ---------------------------------------------------------------- the event

def _event(kind: str, event_id: str, folders: related_matches.Folders) -> dict:
    if kind not in ("inbox", "capture"):
        raise ResearchRefused(404, "Unknown kind of event")
    try:
        event_context.event_key(kind, event_id)
    except ContextRefused as exc:
        raise ResearchRefused(404, str(exc)) from None
    if kind == "inbox":
        item, _, versions = event_links._versions(folders.inbox, event_id)
        if item is None and not versions:
            raise ResearchRefused(404, "No Event Inbox entry with this identifier is held locally")
        entry = item if item is not None else event_overview._version_item(event_id, versions[-1])
        excerpt = None if entry["excerpt_repeats_title"] or not entry["excerpt"] else entry["excerpt"]
        raw = entry["feed_timestamp"]["raw"]
        label = "listing timestamp (retained snapshot)" if entry["source"] in inbox_imports.SOURCES \
            else "feed timestamp"
        return {"kind": kind, "id": event_id, "title": entry["title"], "url": entry["link"],
                "fields": {"title": entry["title"], "excerpt": excerpt}, "date": stated_date(raw), "date_as_stated": raw,
                "date_label": label, "title_only": excerpt is None}
    try:
        record = event_intake.verified(folders.intake, event_id)
    except (event_intake.IntakeRefused, OSError) as exc:
        raise ResearchRefused(404, f"This saved event cannot be read: {exc}") from None
    supplied = record["times"]["published_at_as_supplied"]
    return {"kind": kind, "id": event_id, "title": record["event"]["headline"], "url": record["event"]["source_url"],
            "fields": {"headline": record["event"]["headline"], "source_text": record["source_text"]},
            "date": stated_date(supplied), "date_as_stated": supplied,
            "date_label": "publication time as supplied by the operator", "title_only": False}


def _held_dates(folders: related_matches.Folders) -> dict[str, set]:
    """The dates every held event states for each event-specific address: a reused address shows two dates."""
    held: dict[str, set] = {}
    view = event_inbox.inbox_view(folders.inbox)
    for item in view["items"] + view["retained"] + view["imported"]:
        address = event_address(item["link"])
        if address:
            held.setdefault(address, set()).add(stated_date(item["feed_timestamp"]["raw"]))
    for row in event_intake.listing(folders.intake):
        if not row.get("capture_id") or row.get("state", "").startswith("refused"):
            continue
        try:
            record = event_intake.verified(folders.intake, row["capture_id"])
        except (event_intake.IntakeRefused, OSError):
            continue
        address = event_address(record["event"]["source_url"])
        if address:
            held.setdefault(address, set()).add(stated_date(record["times"]["published_at_as_supplied"]))
    return held


# ---------------------------------------------------------------- links

def _long(day: date) -> str:
    return f"{day.day} {MONTH_NAMES[day.month - 1]} {day.year}"


def _gap(earlier: date, later: date) -> str:
    days = (later - earlier).days
    if days == 0:
        return "on the same day"
    if days < 60:
        return f"{days} day{'s' if days != 1 else ''} earlier"
    months = round(days / 30.44)
    return f"about {months} months earlier"


def _link(relation: str, target: dict, event: dict, explanation: str, differences: list[str],
          unknown: list[str], extra: dict | None = None) -> dict:
    status = dict(target["status"])
    prepared = date.fromisoformat(status["prepared_on"])
    status["written_after_event"] = event["date"] is None or prepared > event["date"]
    status["timing"] = (f"Written on {_long(prepared)}, after this event; it was not available when the event "
                        "happened." if status["written_after_event"] else f"Written on {_long(prepared)}.")
    return {"relation": relation, "relation_label": RELATIONS[relation],
            "target": {"collection": target["collection"], "id": target["id"], "title": target["title"],
                       "category": target["category"], "date": target["date"].isoformat(),
                       "date_as_stated": target["date_as_stated"], "href": target["href"]},
            "explanation": explanation, "differences": differences, "unknown": unknown, "status": status,
            **(extra or {})}


def _same_event(event: dict, targets: list[dict], held: dict[str, set]) -> tuple[list[dict], list[str], set]:
    """The same-event link, notes on why there is none, and cases held back from weaker labels: a case at this
    address whose identity cannot be confirmed is not offered as family or topic either."""
    address = event_address(event["url"])
    if address is None:
        note = ("This event's address does not name one document, so no case can be confirmed as coverage of the "
                "same release.")
        return [], [note] if event["url"] else [], set()
    citing = [target for target in targets if target["address"] == address]
    blocked = {(target["collection"], target["id"]) for target in citing}
    if not citing:
        return [], [], set()
    if len(citing) > 1:
        return [], ["More than one case cites this event's address, so it cannot identify one release; those cases "
                    "are not offered here."], blocked
    target = citing[0]
    if event["date"] is None:
        return [], [f"A case cites this event's address, but this event states no date, so it is not confirmed as "
                    f"coverage of the same release and is not offered here ({target['title']})."], blocked
    dates = held.get(address, set()) | {event["date"]}
    if len(dates) > 1 or event["date"] != target["date"]:
        stated = ", ".join(sorted(day.isoformat() for day in dates if day))
        return [], [f"A case cites this event's address, but the dates disagree (the case: "
                    f"{target['date'].isoformat()}; events at this address: {stated}), so no exact-event label is "
                    "used and the case is not offered here."], blocked
    explanation = (f"Library coverage of this event: the case reads the release at the same address ({address}), "
                   f"published on {_long(target['date'])}, the date this event states ({event['date_label']}). It is "
                   "the library's retrospective reading of the same release, not a separate source and not a "
                   "corroboration.")
    return [_link("same_event", target, event, explanation, [], [], {"address": address})], [], set()


def _family(event: dict, targets: list[dict]) -> tuple[list[dict], int]:
    """The latest case of the event's family on or before its date (targets exclude held-back cases)."""
    placed = family_of(event["title"], event["url"])
    if placed is None or event["date"] is None:
        return [], 0
    slug, document = placed
    members = [target for target in targets if target["family"] and target["family"][0] == slug]
    earlier = sorted((target for target in members if target["date"] <= event["date"]),
                     key=lambda target: (target["date"], target["id"]))
    later = len(members) - len(earlier)
    if not earlier:
        return [], later
    target = earlier[-1]
    case_document = target["family"][1]
    family = FAMILIES[slug]
    explanation = (f"Same release family ({family['label']}): this event is {document_label(slug, document)} dated "
                   f"{_long(event['date'])} ({event['date_label']}); the case reads {document_label(slug, case_document)} of "
                   f"{_long(target['date'])}, the latest case of this family in the library on or before this event's "
                   "date. The family is named in this event's own title and confirmed by its address; it is not "
                   "the same release.")
    differences = [f"The case's release is {_gap(target['date'], event['date'])} than this event."]
    if case_document != document:
        differences.insert(0, f"Different documents: this event is {document_label(slug, document)}, the case "
                              f"{document_label(slug, case_document)}.")
    if target["reference_period"]:
        differences.append(f"The case's reference period, as stated: {target['reference_period']}")
    unknown = ["This entry carries only its title, so what this release says is not compared."] \
        if event["title_only"] else ["Only the release family and dates are compared here, not the content."]
    return [_link("release_family", target, event, explanation, differences, unknown,
                  {"family": {"slug": slug, "label": family["label"], "event_document": document,
                              "case_document": case_document, "more_earlier": len(earlier) - 1}})], later


def _topics(event: dict, targets: list[dict]) -> tuple[list[dict], int]:
    if event["date"] is None:
        return [], 0
    by_id = {target["id"]: target for target in targets if target["collection"] == "library"}
    links, later = [], 0
    for slug, topic in TOPICS.items():
        found = topic_terms(slug, event["fields"])
        if found is None or topic["case"] not in by_id:
            continue
        target = by_id[topic["case"]]
        if target["date"] > event["date"]:
            later += 1
            continue
        by_field: dict[str, list[str]] = {}
        for item in found:
            by_field.setdefault(item["field"], []).append(f"“{item['term']}”")
        named = "; ".join(f"{' and '.join(terms)} in {FIELD_LABELS[field]}" for field, terms in by_field.items())
        explanation = (f"Related research topic ({topic['label']}): this event's own text names {named}; "
                       f"{topic['case_basis']}. {NOT_ANALOGY}")
        differences = [f"The case's article is {_gap(target['date'], event['date'])} than this event, and it is a "
                       "different document."] + ([topic["difference"]] if topic.get("difference") else [])
        links.append(_link("topic", target, event, explanation, differences,
                           ["Whether the two say the same thing about this topic is not compared."],
                           {"topic": {"slug": slug, "label": topic["label"], "found": found}}))
    return links, later


def view(kind: str, event_id: str, folders: related_matches.Folders, library: Path = case_library.LIBRARY_DIR,
         sources: Path = related_cases.SOURCES_DIR) -> dict:
    """The related-research links for one event, selected now from local records. Reads only; nothing is written."""
    event = _event(kind, event_id, folders)
    try:
        targets = _targets(library, folders.cases, sources)
    except case_library.LibraryRefused as exc:
        raise ResearchRefused(exc.status, str(exc)) from None
    except related_cases.RelatedRefused as exc:
        raise ResearchRefused(exc.status, str(exc)) from None
    same, notes, blocked = _same_event(event, targets, _held_dates(folders))
    if not any(target["collection"] == "library" for target in targets):
        notes.append("The case library is not installed here, so no library case can be linked.")
    offered = [target for target in targets if (target["collection"], target["id"]) not in blocked]
    family, later_family = _family(event, offered)
    topics, later_topics = _topics(event, offered)
    shown_above: list[str] = []
    try:
        stored = related_matches.view(kind, event_id, folders)
        if stored["state"] == "checked":
            shown_above = [row["case_id"] for row in stored["match"]["related"]]
    except (related_matches.MatchRefused, ContextRefused, OSError):
        pass  # The historical section reports its own state; nothing here depends on it.
    chosen, seen = [], set()
    for link in sorted(same + family + topics, key=lambda link: ORDER.index(link["relation"])):
        key = (link["target"]["collection"], link["target"]["id"])
        if key in seen or (key[0] == "historical" and key[1] in shown_above):
            continue
        seen.add(key)
        chosen.append(link)
    if event["date"] is None:
        notes.append("This event states no date, so no earlier case can be established and no family or topic link "
                     "is offered.")
    if later_family or later_topics:
        notes.append(f"{later_family + later_topics} later case{'s are' if later_family + later_topics != 1 else ' is'} "
                     "not suggested: this version links only to cases published on or before the event's date.")
    if len(chosen) > MAX_LINKS:
        notes.append(f"{len(chosen) - MAX_LINKS} weaker link{'s are' if len(chosen) - MAX_LINKS != 1 else ' is'} not "
                     "shown.")
    return {"view_version": VIEW_VERSION, "navigation_version": NAVIGATION_VERSION, "kind": kind, "id": event_id,
            "event": {"title": event["title"], "date": event["date"].isoformat() if event["date"] else None,
                      "date_as_stated": event["date_as_stated"], "date_label": event["date_label"],
                      "address": event_address(event["url"]), "title_only": event["title_only"]},
            "links": chosen[:MAX_LINKS], "notes": notes, "shown_in_historical": shown_above,
            "relations": RELATIONS, "hints_used": False, "written": False, "provider_called": False}

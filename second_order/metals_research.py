"""The research notes of the metals page (metals-research-0.2): assistant-written transmission chains and the sourced
passages they rest on, checked for shape and resolved against the figures the page already shows.

The content file (content/metals/research.json) is exactly {research_version, written_by, metals: {chapter id:
{thesis?, uses?, substitution?, recycling?, events?, chains?}}}. Each event is {passage, kind, when}: `when` is the
event's date exactly as its quote gives it ("2025", "September 2025"), so an event from a past report is shown with the
date of what happened, never as current news; resolve refuses a date that its verified quote does not contain. Every link of a chain is one of three kinds:
"measured" (a figure on this page, named by a ref), "stated" (a passage of the copper thesis, which thesis_view checks
against its retained source on every read) or "hypothesis" (neither, and labelled so). Any other key, field or kind
refuses the whole file (ResearchRefused, naming a place and a rule); the view then withholds the research part with
RESEARCH_PROBLEM.

resolve computes nothing new. A measured link shows a figure the USGS or IEA part already holds, formatted, or is
unavailable with the source's own reason; a stated link shows its passage, or is withheld with the thesis's problem
when that passage is not verified. A withheld USGS or IEA part makes every link on it unavailable with the part's
problem. Nothing here reads a retained source, writes, fetches or calls a model.
"""
from pathlib import Path
import re

from . import bis_snapshot, metals_usgs
from .metals_iea_uses import MAPPING

# 0.2: each event carries `when`, the date its quote gives, checked against the verified quote; an IEA figure names
# its base ("(4544 kt of 8000 kt)").
ENGINE = VERSION = "metals-research-0.3"
FILE = "research.json"
WRITTEN_BY = ("Written by the assistant from the figures on this page and retained sources; not reviewed by the "
              "owner.")
RESEARCH_PROBLEM = "The research notes are not in the shape this version reads"
THESIS = "copper"  # The only thesis whose passages the notes may cite.
CHAPTERS = tuple(metals_usgs.chapter_id(name) for name in metals_usgs.CHAPTER_NAMES)
TOP_FIELDS = ("research_version", "written_by", "metals")
METAL_FIELDS = ("thesis", "uses", "substitution", "recycling", "events", "chains")
PASSAGE_LISTS = ("uses", "substitution", "recycling")
CHAIN_FIELDS = ("id", "title", "disruption", "links", "direct", "indirect", "gains_losses", "mitigants", "learned",
                "assumed")
CHAIN_TEXTS = ("title", "disruption", "learned", "assumed")
CHAIN_LISTS = ("direct", "indirect", "mitigants")
LINK_FIELDS = {"measured": ("ref",), "stated": ("passage",), "hypothesis": ()}
STAGES = ("mining", "refining", "reserves")
FIGURES = ("leader", "top3", "hhi", "years")
DIRECTIONS = ("may gain", "may lose")
# Text fields (an object field whose value is text) are 8 to 400 characters; an item of a list field (direct, indirect,
# mitigants) is held to the same plain-text rule and maximum, from one character.
MIN_TEXT, MIN_ITEM, MAX_TEXT, MAX_LABEL = 8, 1, 400, 120
MIN_WHEN, MAX_WHEN = 4, 40
YEAR = re.compile(r"\b(?:19|20)\d\d\b")  # a four-digit year, as a word
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PASSAGE = re.compile(THESIS + r":([a-z0-9]+(?:-[a-z0-9]+)*)")
# An event may also cite a passage of the FCX research; a stated link may not.
EVENT_PASSAGE = re.compile(r"(copper|fcx):([a-z0-9]+(?:-[a-z0-9]+)*)")
MARKUP = re.compile(r"[<>*`#|\[\]]")
NO_RESERVES = "No matching 2025 reserves series"
NO_PAIR = "No years figure for this pair"
NO_RELIANCE = "USGS prints no 2025 net import reliance for this metal"


class ResearchRefused(ValueError):
    """The research notes are not in the shape this version reads. `place` names where, `rule` what was expected."""

    def __init__(self, place, rule):
        super().__init__(place + ": " + rule)
        self.place, self.rule = place, rule


# ---------------------------------------------------------------- the content file, checked

def _require(condition, place, rule):
    if not condition:
        raise ResearchRefused(place, rule)


def _fields(value, place, required, optional=()):
    _require(isinstance(value, dict), place, "expected an object")
    for name in value:
        _require(name in required or name in optional, place, "unknown field " + repr(name))
    for name in required:
        _require(name in value, place, "missing field " + repr(name))
    return value


def _line(value, low, high):
    return (isinstance(value, str) and low <= len(value) <= high and value == value.strip() and "  " not in value
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _text(value, place, low=MIN_TEXT):
    _require(_line(value, low, MAX_TEXT) and not MARKUP.search(value), place,
             f"expected plain text of {low} to {MAX_TEXT} characters on one line, without markup")


def _list(value, place):
    _require(isinstance(value, list) and len(value) > 0, place, "expected a non-empty list")
    return value


def _event_passage(value, place):
    _require(isinstance(value, str) and EVENT_PASSAGE.fullmatch(value) is not None, place,
             f'expected "{THESIS}:<passage id>" or "fcx:<passage id>"')


def _passage(value, place):
    _require(isinstance(value, str) and PASSAGE.fullmatch(value) is not None, place,
             f'expected "{THESIS}:<passage id>"')


def _ref(ref, metal, place):
    _require(isinstance(ref, dict), place, "expected an object")
    keys = set(ref)
    if keys == {"stage", "figure"}:
        _require(ref["stage"] in STAGES, place + ".stage", "expected one of " + ", ".join(STAGES))
        _require(ref["figure"] in FIGURES, place + ".figure", "expected one of " + ", ".join(FIGURES))
        _require(ref["figure"] != "years" or ref["stage"] == "reserves", place + ".figure",
                 "years is a figure of the reserves stage only")
    elif keys == {"reliance"}:
        _require(ref["reliance"] == "2025", place + ".reliance", 'expected "2025"')
    elif keys == {"iea", "technology"}:
        _require(isinstance(ref["iea"], str) and MAPPING.get(ref["iea"], (None,))[0] == metal, place + ".iea",
                 "expected an IEA name that the fixed mapping gives to this metal")
        _require(_line(ref["technology"], 1, MAX_LABEL), place + ".technology",
                 f"expected a technology label of 1 to {MAX_LABEL} characters on one line")
    else:
        raise ResearchRefused(place, "expected {stage, figure}, {reliance} or {iea, technology}")


def _link(link, metal, place):
    _require(isinstance(link, dict), place, "expected an object")
    _require(isinstance(link.get("kind"), str) and link["kind"] in LINK_FIELDS, place + ".kind",
             "expected one of " + ", ".join(LINK_FIELDS))
    _fields(link, place, ("text", "kind") + LINK_FIELDS[link["kind"]])
    _text(link["text"], place + ".text")
    if link["kind"] == "measured":
        _ref(link["ref"], metal, place + ".ref")
    elif link["kind"] == "stated":
        _passage(link["passage"], place + ".passage")


def _chain(chain, metal, place, seen):
    _fields(chain, place, CHAIN_FIELDS)
    _require(isinstance(chain["id"], str) and ID.fullmatch(chain["id"]) is not None, place + ".id",
             "expected a lower-case id of letters, digits and single hyphens")
    _require(chain["id"] not in seen, place + ".id", "a chain id may be used once in the file")
    seen.add(chain["id"])
    for name in CHAIN_TEXTS:
        _text(chain[name], place + "." + name)
    for number, link in enumerate(_list(chain["links"], place + ".links")):
        _link(link, metal, f"{place}.links[{number}]")
    for name in CHAIN_LISTS:  # Their items are short names ("Stocks"): plain, but not held to MIN_TEXT.
        for number, item in enumerate(_list(chain[name], place + "." + name)):
            _text(item, f"{place}.{name}[{number}]", MIN_ITEM)
    for number, item in enumerate(_list(chain["gains_losses"], place + ".gains_losses")):
        where = f"{place}.gains_losses[{number}]"
        _fields(item, where, ("who", "direction", "mechanism"))
        _text(item["who"], where + ".who")
        _require(item["direction"] in DIRECTIONS, where + ".direction", "expected one of " + ", ".join(DIRECTIONS))
        _text(item["mechanism"], where + ".mechanism")


def _metal(entry, metal, place, seen):
    _fields(entry, place, (), METAL_FIELDS)
    if "thesis" in entry:
        _require(entry["thesis"] == THESIS, place + ".thesis", f'expected "{THESIS}"')
    for name in PASSAGE_LISTS:
        if name in entry:
            cited = []
            for number, item in enumerate(_list(entry[name], place + "." + name)):
                where = f"{place}.{name}[{number}]"
                _passage(item, where)
                _require(item not in cited, where, "a passage may be named once in a list")
                cited.append(item)
    if "events" in entry:
        cited = []
        for number, event in enumerate(_list(entry["events"], place + ".events")):
            where = f"{place}.events[{number}]"
            _fields(event, where, ("passage", "kind", "when"))
            _event_passage(event["passage"], where + ".passage")
            _require(event["passage"] not in cited, where + ".passage", "an event's passage may be named once")
            cited.append(event["passage"])
            _text(event["kind"], where + ".kind")
            _require(_line(event["when"], MIN_WHEN, MAX_WHEN) and not MARKUP.search(event["when"])
                     and YEAR.search(event["when"]) is not None, where + ".when",
                     f"expected the event's date as its quote gives it, {MIN_WHEN} to {MAX_WHEN} characters with a year")
    if "chains" in entry:
        for number, chain in enumerate(_list(entry["chains"], place + ".chains")):
            _chain(chain, metal, f"{place}.chains[{number}]", seen)


def validate(content):
    """The content as given, when it is exactly the shape this version reads; else ResearchRefused(place, rule)."""
    _fields(content, FILE, TOP_FIELDS)
    _require(content["research_version"] == VERSION, "research_version", f'expected "{VERSION}"')
    _require(content["written_by"] == WRITTEN_BY, "written_by", "expected the fixed written-by sentence")
    _require(isinstance(content["metals"], dict), "metals", "expected an object")
    seen = set()
    for metal, entry in content["metals"].items():
        _require(metal in CHAPTERS, "metals." + metal, "expected the id of a USGS chapter")
        _metal(entry, metal, "metals." + metal, seen)
    return content


def load(folder):
    """The checked content of FILE in ``folder``. Raises ResearchRefused for a file that is missing, unreadable, not
    strict JSON or not the shape this version reads. Reads only."""
    try:
        text = (Path(folder) / FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ResearchRefused(FILE, "the file is not there") from None
    except (OSError, UnicodeDecodeError):
        raise ResearchRefused(FILE, "the file cannot be read as UTF-8 text") from None
    try:
        content = bis_snapshot._strict_json(text, "The research notes")
    except bis_snapshot.SnapshotRefused:
        raise ResearchRefused(FILE, "the file is not strict JSON") from None
    return validate(content)


def _cited(content):
    """(place, passage id) of every passage the notes name, in file order."""
    for metal, entry in content["metals"].items():
        place = "metals." + metal
        for name in PASSAGE_LISTS:
            for number, item in enumerate(entry.get(name, [])):
                yield f"{place}.{name}[{number}]", item
        for number, event in enumerate(entry.get("events", [])):
            yield f"{place}.events[{number}].passage", event["passage"]
        for number, chain in enumerate(entry.get("chains", [])):
            for index, link in enumerate(chain["links"]):
                if link["kind"] == "stated":
                    yield f"{place}.chains[{number}].links[{index}].passage", link["passage"]


def passage_refs(content):
    """The full references ("copper:..." or "fcx:...") the (checked) notes cite, each once, in the order first cited."""
    return list(dict.fromkeys(item for _, item in _cited(content)))


def passage_ids(content):
    """The copper thesis's passage ids the (checked) notes cite, each once, in the order first cited."""
    return [ref.split(":", 1)[1] for ref in passage_refs(content) if ref.startswith(THESIS + ":")]


# ---------------------------------------------------------------- the links, resolved

def _grouped(whole):
    return f"{int(whole):,}"


def _order(top, figure):
    """A leader ("Chile 23.0%") or top three ("48.7% (Chile, Congo (Kinshasa), Peru)"), or why it is withheld."""
    if top["shown"] is None:
        return None, top["reason"]
    if figure == "leader":
        return top["countries"][0] + " " + top["shown"] + "%", None
    return top["shown"] + "% (" + ", ".join(top["countries"]) + ")", None


def _hhi(indicators):
    if indicators["hhi_low"] is None:
        return None, indicators["reason"]
    low, high = _grouped(indicators["hhi_low"]), _grouped(indicators["hhi_high"])
    return (low if low == high else low + "–" + high), None


def _years(pair):
    if pair is None:
        return None, NO_PAIR
    if pair["shown"] is None:
        return None, pair["reason"]
    one = pair["shown"] in ("1", metals_usgs.YEARS_UNDER_ONE)
    return pair["shown"] + (" year" if one else " years"), None


def _reserves(chapter, entry):
    """(reserves series, years entry or None) by ruling R1, or (None, None) when no series matches."""
    by_id = {item["id"]: item for item in chapter["series"]}
    mining = next((stage for stage in entry["stages"] if stage["stage"] == "mining"), None)
    if mining is not None:
        for pair in chapter["years_of_reserves"]:
            if pair["production"] == mining["series"]:
                return by_id[pair["reserves"]], pair
    found = [item for item in chapter["series"] if item["statistic"] == "Reserves" and item["year"] == "2025"]
    return (found[0], None) if len(found) == 1 else (None, None)


def _usgs(ref, chapter, entry):
    if "reliance" in ref:
        reliance = entry["us"]["reliance"]
        if reliance is None:
            return None, NO_RELIANCE
        value = reliance["value"]
        return (value + "%" if metals_usgs.number(value) is not None else value), None
    stage, figure = ref["stage"], ref["figure"]
    if stage == "reserves":
        top, pair = _reserves(chapter, entry)  # A series: its leader and top3, and its id.
        if top is None:
            return None, NO_RESERVES
        if figure == "years":
            return _years(pair)
        series_id = top["id"]
    else:
        top = next((item for item in entry["stages"] if item["stage"] == stage), None)  # A stage: the same, by series.
        if top is None:
            return None, f"USGS prints no 2025 production series at the {stage} stage for this metal"
        series_id = top["series"]
    if figure == "hhi":
        return _hhi(entry["series"][series_id])
    return _order(top[figure], figure)


def _iea(ref, metal, uses):
    found = next((item for item in uses if item["name"] == ref["iea"] and item["chapter"] == metal), None)
    if found is not None and found["technologies"] is None:
        return None, f"The IEA's table gives no technology split for {ref['iea']}"
    technologies = (found or {}).get("technologies") or []
    technology = next((item for item in technologies if item["label"] == ref["technology"]), None)
    if technology is None:
        return None, f"The IEA lists no {ref['technology']} use for {ref['iea']} in this table"
    if technology["share_2025"] is None:
        return None, (f"The IEA's 2025 energy-technology total for {ref['iea']} is not positive, so no share is "
                      "computed")
    return (technology["share_2025"] + "% of 2025 energy-technology demand (" + technology["values"]["2025"]
            + " kt of " + found["total"]["2025"] + " kt)"), None


def _withheld(part, problem):
    return f"The {part} part is withheld" + (": " + problem if problem else "")


class _Resolver:
    def __init__(self, chapters, risk, uses, passages, usgs_problem, uses_problem):
        self.usgs = None if chapters is None or risk is None else (
            {item["id"]: item for item in chapters}, {item["id"]: item for item in risk})
        self.uses, self.passages = uses, passages
        self.usgs_problem, self.uses_problem = usgs_problem, uses_problem

    def measured(self, ref, metal):
        if "iea" in ref:
            if self.uses is None:
                return None, _withheld("IEA", self.uses_problem)
            return _iea(ref, metal, self.uses)
        if self.usgs is None:
            return None, _withheld("USGS", self.usgs_problem)
        chapters, risk = self.usgs
        return _usgs(ref, chapters[metal], risk[metal])

    def evidence(self, item):
        return dict(self.passages[item])

    def cited(self, item):
        return {"passage": item, "evidence": self.evidence(item)}

    def link(self, link, metal):
        if link["kind"] == "measured":
            shown, unavailable = self.measured(link["ref"], metal)
            return {"text": link["text"], "kind": "measured", "ref": dict(link["ref"]), "shown": shown,
                    "unavailable": unavailable}
        if link["kind"] == "stated":
            evidence = self.evidence(link["passage"])
            return {"text": link["text"], "kind": "stated", "passage": link["passage"], "evidence": evidence,
                    "unavailable": evidence["problem"] if evidence["state"] != "verified" else None}
        return {"text": link["text"], "kind": "hypothesis"}

    def chain(self, chain, metal):
        return {"id": chain["id"], "title": chain["title"], "disruption": chain["disruption"],
                "links": [self.link(link, metal) for link in chain["links"]], "direct": list(chain["direct"]),
                "indirect": list(chain["indirect"]), "gains_losses": [dict(item) for item in chain["gains_losses"]],
                "mitigants": list(chain["mitigants"]), "learned": chain["learned"], "assumed": chain["assumed"]}

    def event(self, event, place):
        """An event with its date and evidence; a verified quote must contain the date exactly as written."""
        cited = self.cited(event["passage"])
        quote = cited["evidence"]["quote"]
        _require(cited["evidence"]["state"] != "verified" or quote is None or event["when"] in quote, place + ".when",
                 "the event's date is not in its verified quote")
        return {"kind": event["kind"], "when": event["when"], **cited}

    def metal(self, entry, metal):
        events = [self.event(event, f"metals.{metal}.events[{number}]")
                  for number, event in enumerate(entry.get("events", []))]
        return {"thesis": entry.get("thesis"),
                **{name: [self.cited(item) for item in entry.get(name, [])] for name in PASSAGE_LISTS},
                "events": events, "chains": [self.chain(chain, metal) for chain in entry.get("chains", [])]}


def resolve(content, chapters, risk, uses, passages, *, usgs_problem=None, uses_problem=None):
    """{"written_by", "metals": {chapter id: {"thesis", "uses", "substitution", "recycling", "events", "chains"}}},
    every measured link given `shown` or `unavailable`, every cited passage its evidence (thesis_view.passages).

    `chapters` and `risk` are metals_usgs.read and metals_risk.read, or both None when the USGS part is withheld
    (`usgs_problem` says why); `uses` is metals_iea_uses.read, or None when the IEA part is withheld (`uses_problem`).
    `passages` maps each full reference ("copper:<id>", "fcx:<id>") to a thesis_view.passages-shaped entry. Raises ResearchRefused when the content
    is not the shape this version reads or cites a passage `passages` does not hold."""
    validate(content)
    for place, item in _cited(content):
        _require(item in passages, place, "names no passage of the current " + item.split(":", 1)[0] + " research")
    resolver = _Resolver(chapters, risk, uses, passages, usgs_problem, uses_problem)
    return {"written_by": content["written_by"],
            "metals": {metal: resolver.metal(entry, metal) for metal, entry in content["metals"].items()}}

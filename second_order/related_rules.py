"""Related Cases matching rules (related-match-rules-0.1): a fixed vocabulary and one deterministic rule.

Pure functions only: nothing here reads files, calls a model or touches the network. An event's own text (an Inbox
entry's title and feed excerpt, or a capture's headline, supplied source text and source address) is scanned for the
terms below; a saved headline classification, when one is used, is scanned the same way but every term found in it is
marked as a hint. Terms are whole words or phrases, matched without regard to letter case except where a pattern
says otherwise (acronyms such as PRC, OFAC and Entity List keep their case). Terms are evidence that a text names a
dimension; they are not a reading of what the text means.

Four dimensions are tagged: the policy instrument, the sector, the country (or area) and the issuing agency. A case
declares its own values, each tied to facts quoted from its retained source (see related_cases).

The rule, for each case in the collection's order:
    shared[d] = event values of d  intersect  case values of d,   for d in instrument, sector, geography, agency
    related      if shared[instrument] and (shared[sector] or shared[geography])
    not related, but listed as an overlap
                 if any of shared[instrument], shared[sector], shared[geography] is non-empty
    not listed   otherwise (a shared agency alone is not an overlap)
Related cases are ordered by the number of shared dimensions (agency included), most first, then by the collection's
order. There is no score, threshold, probability or ranking beyond that. A related case "rests on a hint" when its
shared instrument, or every shared sector and country that qualifies it, was found only in a saved classification.
"What differs" is stated only from values the event's text names; a dimension the event does not name is unknown.
"""
import re
from urllib.parse import urlsplit

RULES_VERSION = "related-match-rules-0.1"
DIMENSIONS = ("instrument", "sector", "geography", "agency")
DIMENSION_LABELS = {"instrument": "policy instrument", "sector": "sector", "geography": "country or area",
                    "agency": "issuing agency"}
# The word boundary used for every term: no letter, digit or underscore immediately before or after.
_EDGE_BEFORE, _EDGE_AFTER = r"(?<![^\W_])", r"(?![^\W_])"
APOSTROPHE = "['’]"

VOCABULARY = {
    "instrument": {
        "export-controls": ("Export controls", (
            r"export[- ]controls?", r"export (?:restrictions?|curbs?|bans?)", r"(?-i:Entity List)",
            r"(?-i:Unverified List)", r"Export Administration Regulations", r"Commerce Control List",
            r"foreign[- ]direct[- ]product rules?")),
        "sanctions": ("Sanctions", (
            r"sanction(?:s|ed|ing)?", r"Office of Foreign Assets Control", r"(?-i:OFAC)",
            r"Specially Designated Nationals", r"(?-i:SDN) List")),
    },
    "sector": {
        "semiconductors": ("Semiconductors and advanced computing", (
            r"semiconductors?", r"(?<!blue-)(?<!blue )(?:micro)?chips?", r"chipmak(?:ers?|ing)",
            r"integrated circuits?", r"advanced computing", r"supercomput(?:ers?|ing)")),
        "oil": ("Oil and petroleum", (
            r"(?<!palm )(?<!olive )(?<!vegetable )(?<!soybean )(?<!edible )(?<!cooking )oil", r"petroleum",
            r"refiner(?:y|ies|s)?")),
    },
    "geography": {
        "prc": ("China (PRC)", (r"China", r"Chinese", r"(?-i:PRC)", rf"People{APOSTROPHE}s Republic of China")),
        "venezuela": ("Venezuela", (r"Venezuelan?s?",)),
        "russia": ("Russia", (r"Russian?s?",)),
        "iran": ("Iran", (r"Iran(?:ian)?s?",)),
        "north-korea": ("North Korea", (r"North Korean?s?", r"(?-i:DPRK)")),
        "south-korea": ("South Korea", (r"South Korean?s?", r"Republic of Korea")),
        "cuba": ("Cuba", (r"Cuban?s?",)),
        "syria": ("Syria", (r"Syrian?s?",)),
        "uae": ("United Arab Emirates", (r"United Arab Emirates", r"(?-i:UAE)")),
        "taiwan": ("Taiwan", (r"Taiwan(?:ese)?",)),
        "hong-kong": ("Hong Kong", (r"Hong Kong",)),
        "japan": ("Japan", (r"Japan(?:ese)?",)),
        "netherlands": ("Netherlands", (r"Netherlands", r"Dutch")),
        "india": ("India", (r"India(?:n|ns)?",)),
        "mexico": ("Mexico", (r"Mexic(?:o|an|ans)",)),
        "canada": ("Canada", (r"Canad(?:a|ian|ians)",)),
        "european-union": ("European Union", (r"European Union",)),
        "saudi-arabia": ("Saudi Arabia", (r"Saudi Arabia(?:n|ns)?",)),
        "ukraine": ("Ukraine", (r"Ukrain(?:e|ian|ians)",)),
        "middle-east": ("Middle East", (r"Middle East(?:ern)?",)),
    },
    "agency": {
        "bis": ("Commerce Department, Bureau of Industry and Security (BIS)", (
            r"Bureau of Industry and Security", r"Department of Commerce", r"Commerce Department")),
        "treasury": ("Treasury Department, Office of Foreign Assets Control (OFAC)", (
            r"Department of the Treasury", r"Treasury Department", r"Office of Foreign Assets Control",
            r"(?-i:OFAC)")),
    },
}
# A capture's source address names the agency when it is on one of its hosts (the address is operator-supplied).
AGENCY_HOSTS = {"bis": ("www.bis.gov", "bis.gov", "www.commerce.gov", "bis.doc.gov"),
                "treasury": ("home.treasury.gov", "www.treasury.gov", "ofac.treasury.gov")}
HINT_FIELDS = ("hint_event_type", "hint_summary")
FIELD_LABELS = {"title": "the entry's title", "excerpt": "the feed excerpt", "headline": "the capture's headline",
                "source_text": "the source text supplied with the capture", "source_host": "the capture's source address",
                "hint_event_type": "the saved classification's event type (a hint)",
                "hint_summary": "the saved classification's summary (a hint)"}
MAX_OCCURRENCES = 3  # Shown per value; the rule needs only one.

_PATTERNS = {dimension: {slug: [re.compile(_EDGE_BEFORE + pattern + _EDGE_AFTER, re.IGNORECASE) for pattern in terms]
                         for slug, (_, terms) in values.items()} for dimension, values in VOCABULARY.items()}


def label(dimension: str, slug: str) -> str:
    return VOCABULARY[dimension][slug][0]


def slugs(dimension: str) -> set[str]:
    return set(VOCABULARY[dimension])


def tag(fields: dict[str, str | None]) -> dict[str, dict[str, list[dict]]]:
    """Each dimension's values named in the given fields, with what was found where (in field order, then text order).

    ``fields`` maps a field name (FIELD_LABELS) to its text, or None when the input has no such text. The field
    "source_host" holds a host name and is read only for agencies."""
    found: dict[str, dict[str, list[dict]]] = {dimension: {} for dimension in DIMENSIONS}
    for field, text in fields.items():
        if not text:
            continue
        if field == "source_host":
            for slug, hosts in AGENCY_HOSTS.items():
                if text in hosts:
                    found["agency"].setdefault(slug, []).append({"term": text, "field": field,
                                                                 "hint": False})
            continue
        for dimension in DIMENSIONS:
            for slug, patterns in _PATTERNS[dimension].items():
                matches = sorted({(match.start(), match.group(0)) for pattern in patterns
                                  for match in pattern.finditer(text)})
                seen = {item["term"].casefold() for item in found[dimension].get(slug, [])
                        if item["field"] == field}
                for _, term in matches:
                    if term.casefold() in seen:
                        continue
                    seen.add(term.casefold())
                    found[dimension].setdefault(slug, []).append({"term": term, "field": field,
                                                                  "hint": field in HINT_FIELDS})
    return {dimension: {slug: found[dimension][slug] for slug in sorted(found[dimension])}
            for dimension in DIMENSIONS}


def source_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlsplit(url).hostname or "").lower() or None
    except ValueError:
        return None


def _names(dimension: str, values) -> list[str]:
    return [label(dimension, slug) for slug in sorted(values)]


def _shown(occurrences: list[dict]) -> list[dict]:
    return occurrences[:MAX_OCCURRENCES]


def _differences(event: dict, case_tags: dict, shared: dict) -> tuple[list[dict], list[dict]]:
    """What the event's own values show to differ from the case, and which of the case's dimensions it leaves unknown."""
    differs, unknown = [], []
    for dimension in ("instrument", "sector", "geography", "agency"):
        named, theirs = set(event[dimension]), set(case_tags[dimension])
        if not theirs:
            continue
        extra = sorted(named - theirs)
        if named and not shared[dimension]:
            differs.append({"dimension": dimension, "kind": "different", "event": _names(dimension, named),
                            "case": _names(dimension, theirs)})
        elif extra:
            differs.append({"dimension": dimension, "kind": "also_names", "event": _names(dimension, extra),
                            "case": _names(dimension, theirs)})
        elif not named:
            unknown.append({"dimension": dimension, "case": _names(dimension, theirs)})
    return differs, unknown


def _rests_on_hint(event: dict, shared: dict) -> bool:
    def only_hint(dimension: str, slug: str) -> bool:
        return all(item["hint"] for item in event[dimension][slug])

    instrument = all(only_hint("instrument", slug) for slug in shared["instrument"])
    qualifiers = [(dimension, slug) for dimension in ("sector", "geography") for slug in shared[dimension]]
    return instrument or all(only_hint(dimension, slug) for dimension, slug in qualifiers)


def match(event: dict, cases: list[dict]) -> dict:
    """The rule above applied to every case. ``event`` is a tag() result; each case has id and tags
    ({dimension: [slugs]}), in the collection's order. Returns related cases and listed overlaps, explained."""
    related, overlaps = [], []
    for position, case in enumerate(cases):
        case_tags = {dimension: set(case["tags"][dimension]) for dimension in DIMENSIONS}
        shared = {dimension: sorted(set(event[dimension]) & case_tags[dimension]) for dimension in DIMENSIONS}
        evidence = [{"dimension": dimension, "value": slug, "label": label(dimension, slug),
                     "found": _shown(event[dimension][slug])} for dimension in DIMENSIONS for slug in shared[dimension]]
        if shared["instrument"] and (shared["sector"] or shared["geography"]):
            differs, unknown = _differences(event, case_tags, shared)
            related.append({"case_id": case["id"], "position": position,
                            "shared_dimensions": sum(1 for dimension in DIMENSIONS if shared[dimension]),
                            "shared": evidence, "differs": differs, "unknown": unknown,
                            "rests_on_hint": _rests_on_hint(event, shared)})
        elif shared["instrument"] or shared["sector"] or shared["geography"]:
            missing = "sector_or_country" if shared["instrument"] else "instrument"
            overlaps.append({"case_id": case["id"], "shared": evidence, "missing": missing,
                             "case_instruments": _names("instrument", case_tags["instrument"]),
                             "case_sectors_and_countries": _names("sector", case_tags["sector"]) +
                             _names("geography", case_tags["geography"])})
    related.sort(key=lambda row: (-row["shared_dimensions"], row["position"]))
    for row in related:
        del row["position"]
    return {"related": related, "overlaps": overlaps}

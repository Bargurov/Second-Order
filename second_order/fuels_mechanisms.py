"""Committed mechanism content of the fuels page: Market Drivers and Economic Transmission (fuels-mechanisms-0.1).

content/fuels/drivers.json and content/fuels/transmission.json hold general economic mechanisms. They are checked
strictly on every read: exact field sets, fixed item order, https sources, and text rules that keep the prose free of
figures and of attribution or forecast phrasing. A refusal names the file, the item and the field, never the text.
Nothing here fetches.
"""
import re
from datetime import date
from pathlib import Path

from . import bis_snapshot
from .fuels_notes import AUTHORS, REFUSED_PHRASES, REVIEW_FIELDS, refused_phrase
from .fuels_sources import FuelsRefused, _bad, _check, _day, _fields, _https

MECHANISMS_VERSION = "fuels-mechanisms-0.1"
DRIVER_IDS = ("opec_supply", "global_demand", "inventories", "refining", "geopolitics", "shipping",
              "dollar_rates_growth", "seasonality")
SECTOR_IDS = ("aviation", "shipping_logistics", "refiners_energy", "chemicals", "agriculture", "consumer_retail",
              "inflation_policy")
ACTS_ON = ("crude", "crack", "both")
EFFECTS = ("negative", "positive", "mixed")
DRIVERS_FILE = "drivers.json"
TRANSMISSION_FILE = "transmission.json"
MAX_FILE_BYTES = 200_000
MAX_SOURCES = 10
MAX_TITLE, MAX_MECHANISM, MAX_ENTRY, MAX_STEP, MAX_SOURCE_TEXT = 80, 600, 240, 60, 200
TOP_FIELDS = {"mechanisms_version", "kind", "prepared_on", "author", "review", "items"}
DRIVER_FIELDS = {"id", "title", "mechanism", "acts_on", "direction", "changes_when", "watch", "sources"}
TRANSMISSION_FIELDS = {"id", "sector", "trigger", "chain", "effect", "effect_text", "second_order", "flips_when",
                       "lag", "lag_sourced", "sources"}
SOURCE_FIELDS = {"title", "publisher", "date", "url", "checked_on", "locator"}
# REFUSED_PHRASES and refused_phrase come from fuels_notes, so the notes and these files share one phrase rule.
# A four-digit token from 1900 to 2099 passes the digit rule even as a quantity, not a year; review catches that.
_ALLOWED_NUMBERS = re.compile(r"\b(?:19|20)\d{2}\b|(?<![\w-])3-2-1(?![\w-])")
# Mechanism prose only (the situation note describes the current prices by design, so it keeps the shared rule): a
# general mechanism must never read as the account of the current move (rule 1), so it may not point at a time,
# narrate a price move in the past tense or forecast. EIA's publication "This Week in Petroleum" is a name, not a time.
GENERAL_ONLY_REFUSED = (
    "recent", "recently", "currently", "now", "lately", "latest", "so far", "amid", "today", "this month",
    "this quarter", "this year", "last week", "last month", "last quarter", "last year", "current move",
    "current rise", "current fall", "current rally", "current decline", "current spike",
    "rose", "risen", "fell", "fallen", "jumped", "surged", "plunged", "slumped", "soared", "widened", "narrowed",
    "climbed", "dropped", "tumbled", "spiked", "rallied", "lifted", "pushed", "spurred", "sparked", "fuelled",
    "fueled", "boosted",
    "on the back of", "thanks to", "owing to", "resulted in", "drives", "will", "likely to", "set to", "poised to")
_GENERAL_ONLY = re.compile(r"(?<!\w)(?:this\s+week(?!\s+in\s+petroleum)|"
                           + "|".join(r"\s+".join(map(re.escape, p.split())) for p in GENERAL_ONLY_REFUSED)
                           + r")(?!\w)", re.IGNORECASE)


def check_text(value: object, where: str, limit: int, *, digits: bool = True, phrases: bool = True) -> str:
    """Non-empty text within the limit; unless phrases is False, none of the refused phrases and nothing that points at
    a time, narrates a move or forecasts; unless digits is False, no digits except four-digit years and the token
    3-2-1. A refusal names where, never the text."""
    _check(isinstance(value, str) and 0 < len(value) <= limit, where, "expected non-empty text of limited length")
    if phrases:
        _check(not refused_phrase(value), where, "attribution and forecast phrasing is not allowed")
        _check(not _GENERAL_ONLY.search(value), where,
               "a general mechanism may not point at a time, narrate a price move or forecast")
    if digits:
        _check(not re.search(r"\d", _ALLOWED_NUMBERS.sub("", value)), where,
               "numbers belong to code: no digits except years and 3-2-1")
    return value


def _list(value: object, where: str, limit: int, minimum: int = 1) -> list:
    _check(isinstance(value, list) and minimum <= len(value) <= 20, where, "expected a short list of enough entries")
    for index, entry in enumerate(value):
        check_text(entry, f"{where}[{index}]", limit)
    return value


def _source(source: object, where: str, prepared: date) -> None:
    """A cited source. Its title and locator quote the source verbatim, so they are exempt from the digit rule and the
    refused phrases (the phrases protect this project's own prose, not other publishers' titles); the publisher is
    exempt from the digit rule only."""
    _fields(source, SOURCE_FIELDS, where)
    check_text(source["title"], f"{where}.title", MAX_SOURCE_TEXT, digits=False, phrases=False)
    check_text(source["publisher"], f"{where}.publisher", MAX_SOURCE_TEXT, digits=False)
    if source["date"] is not None:
        _day(source["date"], f"{where}.date")
    _https(source["url"], f"{where}.url")
    _check(_day(source["checked_on"], f"{where}.checked_on") <= prepared, f"{where}.checked_on",
           "expected a date not after prepared_on")
    if source["locator"] is not None:
        check_text(source["locator"], f"{where}.locator", MAX_SOURCE_TEXT, digits=False, phrases=False)


def _sources(value: object, where: str, prepared: date) -> list:
    _check(isinstance(value, list) and len(value) <= MAX_SOURCES, where, "expected a short list")
    for index, source in enumerate(value):
        _source(source, f"{where}[{index}]", prepared)
    return value


def _driver(item: dict, where: str, prepared: date) -> None:
    check_text(item["title"], f"{where}.title", MAX_TITLE)
    check_text(item["mechanism"], f"{where}.mechanism", MAX_MECHANISM)
    _check(isinstance(item["acts_on"], str) and item["acts_on"] in ACTS_ON, f"{where}.acts_on",
           "expected a listed value")
    for name in ("direction", "changes_when", "watch"):
        _list(item[name], f"{where}.{name}", MAX_ENTRY)
    _sources(item["sources"], f"{where}.sources", prepared)


def _transmission(item: dict, where: str, prepared: date) -> None:
    check_text(item["sector"], f"{where}.sector", MAX_TITLE)
    check_text(item["trigger"], f"{where}.trigger", MAX_TITLE)
    _list(item["chain"], f"{where}.chain", MAX_STEP, minimum=3)
    _check(isinstance(item["effect"], str) and item["effect"] in EFFECTS, f"{where}.effect", "expected a listed value")
    check_text(item["effect_text"], f"{where}.effect_text", MAX_MECHANISM)
    for name in ("second_order", "flips_when"):
        _list(item[name], f"{where}.{name}", MAX_ENTRY)
    check_text(item["lag"], f"{where}.lag", MAX_ENTRY)
    _check(type(item["lag_sourced"]) is bool, f"{where}.lag_sourced", "expected true or false")
    sources = _sources(item["sources"], f"{where}.sources", prepared)
    _check(not item["lag_sourced"] or bool(sources), f"{where}.lag_sourced", "expected a listed source when true")


def _check_file(raw: object, name: str, kind: str, ids: tuple, fields: set, check_item) -> dict:
    _fields(raw, TOP_FIELDS, name)
    _check(raw["mechanisms_version"] == MECHANISMS_VERSION, f"{name}.mechanisms_version",
           "expected the supported version")
    _check(raw["kind"] == kind, f"{name}.kind", f"expected {kind}")
    prepared = _day(raw["prepared_on"], f"{name}.prepared_on")
    _check(isinstance(raw["author"], str) and raw["author"] in AUTHORS, f"{name}.author", "expected a listed author")
    review = _fields(raw["review"], REVIEW_FIELDS, f"{name}.review")
    _check(isinstance(review["state"], str) and review["state"] in ("unreviewed", "reviewed"),
           f"{name}.review.state", "expected unreviewed or reviewed")
    if review["state"] == "unreviewed":
        _check(review["reviewed_on"] is None, f"{name}.review.reviewed_on", "expected null while unreviewed")
    else:
        reviewed = _day(review["reviewed_on"], f"{name}.review.reviewed_on")
        _check(reviewed >= prepared, f"{name}.review.reviewed_on", "expected a date not before prepared_on")
    items = raw["items"]
    _check(isinstance(items, list) and len(items) == len(ids), f"{name}.items", "expected exactly the listed items")
    for index, (item, item_id) in enumerate(zip(items, ids)):
        _check(isinstance(item, dict) and item.get("id") == item_id, f"{name}.items[{index}].id",
               "expected the items in their fixed order")
        where = f"{name} {item_id}"
        _fields(item, fields, where)
        check_item(item, where, prepared)
    return raw


def _load(content: Path, name: str, kind: str, ids: tuple, fields: set, check_item) -> dict | None:
    path = Path(content) / name
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise _bad(name, "the file is larger than the limit")
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        raise _bad(name, "the file cannot be read") from None
    try:
        raw = bis_snapshot._strict_json(text, name)
    except bis_snapshot.SnapshotRefused:
        raise _bad(name, "the file is not strict JSON") from None
    return _check_file(raw, name, kind, ids, fields, check_item)


def load_drivers(content: Path) -> dict | None:
    """The checked drivers file, or None when absent. An invalid file raises FuelsRefused(500)."""
    return _load(content, DRIVERS_FILE, "drivers", DRIVER_IDS, DRIVER_FIELDS, _driver)


def load_transmission(content: Path) -> dict | None:
    """The checked transmission file, or None when absent. An invalid file raises FuelsRefused(500)."""
    return _load(content, TRANSMISSION_FILE, "transmission", SECTOR_IDS, TRANSMISSION_FIELDS, _transmission)

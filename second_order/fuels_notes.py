"""The committed "situation now" notes of the fuels page (fuels-note-0.1 and fuels-note-0.2).

A note is prose the owner or Claude wrote on a given day, bound to the price snapshot and observation date it was
written for. Prices never appear as digits in the prose: placeholders are filled by code from the bound snapshot, and
a digit rule keeps numbers out of the text. The refused causal and forecast phrases, shared with the mechanism files,
are refused in the prose too. A refusal names the file and field, never a value or quote. Nothing here fetches.

fuels-note-0.1 holds a headline, a lede and three columns (supply, demand, stocks). fuels-note-0.2 keeps the headline
and lede (the lede is the visible summary, at most seventy words) and replaces the columns with an analysis: what
happened, what it may mean, who it may touch and what to check next, each a short list of statements labelled by kind
(an observation, a computed figure, a possible explanation, a sourced claim or a projection attributed to its source),
plus caveats. Its placeholders add the week and month windows of Situation Now, computed from the bound snapshot:
dates, changes, percent changes, the direction of each move ("rose", "fell") and the split of the basket's change, so
neither a figure nor a direction is typed by hand. Both versions read; a 0.1 note is unchanged.

A change whose exact value is not zero but rounds to zero at its shown places is filled as "less than" the last shown
place, with its direction from the exact value ("fell less than $0.01 a barrel", "a fall of less than $0.01 a barrel",
"less than 0.1%"), so it is never mistaken for no change; a true zero reads as before.
"""
import re
from datetime import date
from pathlib import Path

from . import bis_snapshot
from .fuels_sources import FuelsRefused

NOTE_VERSION = "fuels-note-0.1"  # headline, lede and three columns
ANALYSIS_VERSION = "fuels-note-0.2"  # headline, summary lede and an analysis in place of the columns
PLACEHOLDERS = ("brent", "crack", "basket", "brent_change")
WINDOWS = ("week", "month")
MEASURES = ("brent", "gasoline", "diesel", "basket", "crack")
ANALYSIS_PLACEHOLDERS = (PLACEHOLDERS
                         + tuple(f"{w}_{part}" for w in WINDOWS
                                 for part in ("from", "to", "split", "gasoline_part", "diesel_part"))
                         + tuple(f"{w}_{m}_{part}" for w in WINDOWS for m in MEASURES for part in ("move", "change"))
                         + tuple(f"{w}_{m}_pct" for w in WINDOWS for m in MEASURES if m != "crack"))
KINDS = ("observation", "computed", "hypothesis", "sourced", "source_projection")
SOURCED_KINDS = ("sourced", "source_projection")
FROM_SNAPSHOT = ("observation", "computed")  # a figure from the snapshot or the engine, never from a source
SECTIONS = {"what_happened": (1, 4), "meaning": (1, 6), "relevance": (1, 2), "watch": (2, 3)}
MAX_ITEM, MAX_CAVEAT, MAX_CAVEATS = 420, 300, 6
SUMMARY_WORDS = (25, 70)  # raw words, a placeholder counted as one; the filled summary is held to forty to seventy
SPLIT_TEXT = {"unchanged": "neither Brent nor the crack changed",
              "offsetting": "Brent's part and the crack's part moved in opposite directions",
              "mostly_crude": "most of the basket's change went with Brent",
              "mostly_crack": "most of the basket's change went with the crack",
              "both": "the basket's change went with both Brent and the crack"}
PER_GALLON = ("gasoline", "diesel")
AUTHORS = ("Claude (AI-drafted)", "Owner")
NOTES_DIR = "notes"
MAX_FILE_BYTES = 100_000
MAX_HEADLINE, MAX_LEDE, MAX_COLUMN = 120, 600, 200
MAX_SOURCES = 20
MINUS = "−"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TOP_FIELDS = {"note_version", "number", "written_on", "covers_through", "snapshot_id", "observation_date", "author",
              "review", "headline", "lede", "columns", "sources"}
ANALYSIS_TOP_FIELDS = (TOP_FIELDS - {"columns"}) | {"analysis"}
ANALYSIS_FIELDS = set(SECTIONS) | {"caveats"}
ITEM_FIELDS = {"kind", "text", "sources", "mechanism"}
REVIEW_FIELDS = {"state", "reviewed_on"}
COLUMN_FIELDS = {"supply", "demand", "stocks"}
SOURCE_FIELDS = {"title", "publisher", "date", "url", "locator"}
_FILE = re.compile(r"situation-([0-9]{4})\.json")
_PLACEHOLDER = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")
_ANALYSIS_PLACEHOLDER = re.compile(r"\{(" + "|".join(ANALYSIS_PLACEHOLDERS) + r")\}")
_NO_PLACEHOLDER = re.compile(r"(?!)")
_MECHANISM = re.compile(r"(transmission|drivers):([a-z][a-z0-9_]{0,40})")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_SNAPSHOT_ID = re.compile(r"[0-9a-f]{64}")
REFUSED_PHRASES = ("caused", "causes", "drove", "driven by", "due to", "because of", "as a result of", "led to",
                   "triggered", "will rise", "will fall", "will increase", "will decrease", "forecast", "expect",
                   "expects", "expected")
_PHRASE = re.compile(r"(?<!\w)(?:" + "|".join(r"\s+".join(map(re.escape, p.split())) for p in REFUSED_PHRASES)
                     + r")(?!\w)", re.IGNORECASE)


def refused_phrase(text: str) -> bool:
    """Whether the text holds a refused causal or forecast phrase: any case, word-bounded, any whitespace (a line break
    or a non-breaking space too) inside a phrase. The one rule for the notes' prose and the mechanism files."""
    return bool(_PHRASE.search(text))


def _bad(where: str, rule: str) -> FuelsRefused:
    return FuelsRefused(500, f"{where}: {rule}")


def _check(ok: bool, where: str, rule: str) -> None:
    if not ok:
        raise _bad(where, rule)


def _fields(value: object, names: set, where: str) -> dict:
    _check(isinstance(value, dict), where, "expected an object")
    _check(set(value) == names, where, "expected exactly the listed fields")
    return value


def _day(value: object, where: str) -> date:
    try:
        _check(isinstance(value, str) and len(value) == 10, where, "expected a date as YYYY-MM-DD")
        return date.fromisoformat(value)
    except ValueError:
        raise _bad(where, "expected a date as YYYY-MM-DD") from None


def _prose(value: object, limit: int, where: str, placeholders: re.Pattern = _PLACEHOLDER) -> str:
    _check(isinstance(value, str) and 0 < len(value) <= limit, where, "expected non-empty text of limited length")
    _check(not refused_phrase(value), where, "causal and forecast phrasing is not allowed")
    rest = placeholders.sub("", value)
    _check("{" not in rest and "}" not in rest, where, "braces may only form a listed placeholder")
    _check(not re.search(r"\d", _YEAR.sub("", rest)), where, "numbers belong to code: no digits except years")
    return value


def _check_analysis(analysis: object, sources: int, label: str) -> None:
    """The analysis of a fuels-note-0.2: four sections of labelled statements and the caveats. A sourced claim or an
    attributed projection names at least one of the note's sources; an observation or a computed figure names none
    (it comes from the snapshot or the engine); a statement of who it may touch names a transmission mechanism; every
    source is cited at least once."""
    where = f"{label}.analysis"
    analysis = _fields(analysis, ANALYSIS_FIELDS, where)
    cited: set = set()
    for section, (low, high) in SECTIONS.items():
        items = analysis[section]
        _check(isinstance(items, list) and low <= len(items) <= high, f"{where}.{section}",
               f"expected {low} to {high} statements")
        for index, item in enumerate(items):
            at = f"{where}.{section}[{index}]"
            _fields(item, ITEM_FIELDS, at)
            _check(isinstance(item["kind"], str) and item["kind"] in KINDS, f"{at}.kind", "expected a listed kind")
            _prose(item["text"], MAX_ITEM, f"{at}.text", _ANALYSIS_PLACEHOLDER)
            refs = item["sources"]
            _check(isinstance(refs, list) and all(type(ref) is int and 0 <= ref < sources for ref in refs)
                   and len(set(refs)) == len(refs), f"{at}.sources", "expected distinct indexes of the note's sources")
            if item["kind"] in SOURCED_KINDS:
                _check(bool(refs), f"{at}.sources", "a sourced statement names its sources")
            if item["kind"] in FROM_SNAPSHOT:
                _check(not refs, f"{at}.sources", "an observation or a computed figure comes from the snapshot")
            cited |= set(refs)
            mechanism = item["mechanism"]
            _check(mechanism is None or (isinstance(mechanism, str) and bool(_MECHANISM.fullmatch(mechanism))),
                   f"{at}.mechanism", "expected null, transmission:<id> or drivers:<id>")
            if section == "relevance":
                _check(isinstance(mechanism, str) and mechanism.startswith("transmission:"), f"{at}.mechanism",
                       "a statement of who it may touch names a transmission mechanism")
    caveats = analysis["caveats"]
    _check(isinstance(caveats, list) and 0 < len(caveats) <= MAX_CAVEATS, f"{where}.caveats",
           f"expected one to {MAX_CAVEATS} caveats")
    for index, caveat in enumerate(caveats):
        _prose(caveat, MAX_CAVEAT, f"{where}.caveats[{index}]", _NO_PLACEHOLDER)
    _check(cited == set(range(sources)), f"{label}.sources", "expected every source to be cited by a statement")


def words(text: str) -> int:
    return len(text.split())


def check_note(raw: object, number: int) -> dict:
    """The note, if it is exactly the committed shape; otherwise FuelsRefused(500) naming the field."""
    label = f"note {number}"
    _check(isinstance(raw, dict), label, "expected an object")
    version = raw.get("note_version")
    _check(version in (NOTE_VERSION, ANALYSIS_VERSION), f"{label}.note_version", "expected the supported version")
    analysed = version == ANALYSIS_VERSION
    note = _fields(raw, ANALYSIS_TOP_FIELDS if analysed else TOP_FIELDS, label)
    _check(type(note["number"]) is int and note["number"] == number, f"{label}.number",
           "expected the number in the file name")
    written = _day(note["written_on"], f"{label}.written_on")
    covers = _day(note["covers_through"], f"{label}.covers_through")
    _check(covers <= written, f"{label}.covers_through", "expected a date not after written_on")
    _check(isinstance(note["snapshot_id"], str) and bool(_SNAPSHOT_ID.fullmatch(note["snapshot_id"])),
           f"{label}.snapshot_id", "expected 64 lower-case hex characters")
    observed = _day(note["observation_date"], f"{label}.observation_date")
    _check(observed <= written, f"{label}.observation_date", "expected a date not after written_on")
    _check(isinstance(note["author"], str) and note["author"] in AUTHORS, f"{label}.author", "expected a listed author")
    review = _fields(note["review"], REVIEW_FIELDS, f"{label}.review")
    _check(review["state"] in ("unreviewed", "reviewed") and isinstance(review["state"], str),
           f"{label}.review.state", "expected unreviewed or reviewed")
    if review["state"] == "unreviewed":
        _check(review["reviewed_on"] is None, f"{label}.review.reviewed_on", "expected null while unreviewed")
    else:
        reviewed = _day(review["reviewed_on"], f"{label}.review.reviewed_on")
        _check(reviewed >= written, f"{label}.review.reviewed_on", "expected a date not before written_on")
    names = _ANALYSIS_PLACEHOLDER if analysed else _PLACEHOLDER
    _prose(note["headline"], MAX_HEADLINE, f"{label}.headline", names)
    _prose(note["lede"], MAX_LEDE, f"{label}.lede", names)
    if analysed:
        low, high = SUMMARY_WORDS
        _check(low <= words(note["lede"]) <= high, f"{label}.lede", f"expected a summary of {low} to {high} words")
    else:
        columns = _fields(note["columns"], COLUMN_FIELDS, f"{label}.columns")
        for name in sorted(COLUMN_FIELDS):
            _prose(columns[name], MAX_COLUMN, f"{label}.columns.{name}")
    sources = note["sources"]
    _check(isinstance(sources, list) and 0 < len(sources) <= MAX_SOURCES, f"{label}.sources",
           "expected a short, non-empty list")
    latest = None
    for index, source in enumerate(sources):
        where = f"{label}.sources[{index}]"
        _fields(source, SOURCE_FIELDS, where)
        for name in ("title", "publisher", "locator"):
            _check(isinstance(source[name], str) and 0 < len(source[name]) <= 300, f"{where}.{name}",
                   "expected non-empty text of limited length")
        day = _day(source["date"], f"{where}.date")
        latest = day if latest is None or day > latest else latest
        url = source["url"]
        _check(isinstance(url, str) and url.startswith("https://") and len(url) <= 300 and url.isascii()
               and " " not in url, f"{where}.url", "expected an https URL")
    _check(covers == latest, f"{label}.covers_through", "expected the latest source date")
    if analysed:
        _check_analysis(note["analysis"], len(sources), label)
    return note


def load_notes(content: Path) -> list[dict]:
    """Every checked note under <content>/notes, ascending by number. No folder means no notes. A situation-* file
    that is not named situation-NNNN.json is refused; other files are ignored."""
    folder = Path(content) / NOTES_DIR
    if not folder.is_dir():
        return []
    found = {}
    for path in folder.iterdir():
        match = _FILE.fullmatch(path.name)
        if match:
            found[int(match.group(1))] = path
        elif path.name.startswith("situation-"):
            raise _bad(f"notes/{path.name}", "expected a name situation-NNNN.json with four digits")
    notes = []
    for expected, number in enumerate(sorted(found), start=1):
        _check(number == expected, f"notes/situation-{number:04d}.json", "expected numbers from 1 with no gaps")
        path = found[number]
        label = f"notes/{path.name}"
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise _bad(label, "the file is larger than the limit")
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            raise _bad(label, "the file cannot be read") from None
        try:
            raw = bis_snapshot._strict_json(text, label)
        except bis_snapshot.SnapshotRefused:
            raise _bad(label, "the file is not strict JSON") from None
        try:
            notes.append(check_note(raw, number))
        except FuelsRefused as refused:
            raise _bad(label, str(refused)) from None
    return notes


def _money(shown: str) -> str:
    """The shown figure as dollars; a negative uses the true minus sign."""
    if shown.startswith("-"):
        return f"{MINUS}${shown[1:]}"
    return f"${shown}"


def _date_text(day: str) -> str:
    when = date.fromisoformat(day)
    return f"{when.day} {MONTHS[when.month - 1]} {when.year}"


def _zero(text: str) -> bool:
    return text.lstrip("-").strip("0.") == ""


def _under(pair: dict) -> bool:
    """A change that is not zero but shows as zero: smaller than the last shown place."""
    return _zero(pair["shown"]) and not _zero(pair["value"])


def _last_place(shown: str) -> str:
    """The smallest step a shown figure can show: "0.00" gives "0.01", "0.000" gives "0.001", "0.0" gives "0.1"."""
    places = len(shown.partition(".")[2])
    return f"0.{'0' * (places - 1)}1" if places else "1"


def _change_text(barrel: dict) -> str:
    change = barrel.get("change")
    if not barrel.get("previous_date") or not change:
        return "with no earlier common observation"
    since = _date_text(barrel["previous_date"])
    moved = change["brent"]
    if _zero(moved["value"]):
        return f"unchanged since {since}"
    if _under(moved):
        way = "down" if moved["value"].startswith("-") else "up"
        return f"{way} less than ${_last_place(moved['shown'])} since {since}"
    sign = MINUS if moved["value"].startswith("-") else "+"
    return f"{sign}${moved['shown'].lstrip('-')} since {since}"


class Unfillable(Exception):
    """A placeholder names a window the bound snapshot does not compute."""

    def __init__(self, window: str):
        super().__init__(window)
        self.window = window


def _move(value: str) -> str:
    if _zero(value):
        return "was unchanged"
    return "fell" if value.startswith("-") else "rose"


def _amount(pair: dict, measure: str) -> str:
    """A change's size without its sign (the move says which way), in its unit; under the last shown place, "less
    than" that place."""
    shown = pair["shown"]
    size = f"less than ${_last_place(shown)}" if _under(pair) else f"${shown.lstrip('-')}"
    return f"{size} " + ("a gallon" if measure in PER_GALLON else "a barrel")


def _signed(pair: dict) -> str:
    """A part of the basket's change with its sign (the true minus, or a plus), per barrel of crude; under the last
    shown place, a fall or a rise of less than that place."""
    if _under(pair):
        way = "fall" if pair["value"].startswith("-") else "rise"
        return f"a {way} of less than ${_last_place(pair['shown'])} a barrel"
    plus = "" if pair["shown"].startswith("-") or _zero(pair["value"]) else "+"
    return plus + _money(pair["shown"]) + " a barrel"


def _percent(row: dict) -> str:
    """A percent change without its sign; under the last shown place (a change that is not zero), "less than" it."""
    shown = row["pct"]["shown"]
    if _zero(shown) and not _zero(row["change"]["value"]):
        return f"less than {_last_place(shown)}%"
    return shown.lstrip("-") + "%"


def window_values(situation: dict | None, window_id: str) -> dict | None:
    """The placeholders of one Situation Now window, or None when the window is not computed."""
    window = next((w for w in (situation or {}).get("windows", []) if w.get("id") == window_id), None)
    if window is None or window.get("state") != "computed":
        return None
    rows, split = window["rows"], window["split"]
    values = {f"{window_id}_from": _date_text(window["from"]), f"{window_id}_to": _date_text(window["to"]),
              f"{window_id}_split": SPLIT_TEXT[split["label"]],
              f"{window_id}_gasoline_part": _signed(split["gasoline_part"]),
              f"{window_id}_diesel_part": _signed(split["diesel_part"])}
    for measure in MEASURES:
        change = rows[measure]["change"]
        values[f"{window_id}_{measure}_move"] = _move(change["value"])
        values[f"{window_id}_{measure}_change"] = _amount(change, measure)
        if measure != "crack" and rows[measure]["pct"] is not None:
            values[f"{window_id}_{measure}_pct"] = _percent(rows[measure])
    return values


def fill(text: str, barrel: dict, situation: dict | None = None) -> str:
    """The prose with each placeholder replaced by the figure of a computed barrel, or of a computed Situation Now
    window of the same snapshot; Unfillable when it names a window (or a percent) the snapshot does not compute."""
    values = {
        "brent": _money(barrel["inputs"]["brent"]["shown"]),
        "basket": _money(barrel["basket"]["shown"]),
        "crack": _money(barrel["crack"]["shown"]),
        "brent_change": _change_text(barrel),
    }
    for window_id in WINDOWS:
        values |= window_values(situation, window_id) or {}

    def value(found: re.Match) -> str:
        name = found.group(1)
        if name not in values:
            raise Unfillable(name.split("_", 1)[0])
        return values[name]
    return _ANALYSIS_PLACEHOLDER.sub(value, text)


def _prose_fields(note: dict, barrel: dict | None, situation: dict | None = None) -> dict:
    def put(text: str) -> str:
        return text if barrel is None else fill(text, barrel, situation)
    filled = {**note, "headline": put(note["headline"]), "lede": put(note["lede"])}
    if "columns" in note:
        filled["columns"] = {name: put(text) for name, text in note["columns"].items()}
    if "analysis" in note:
        filled["analysis"] = {section: [{**item, "text": put(item["text"])} for item in note["analysis"][section]]
                              for section in SECTIONS} | {"caveats": list(note["analysis"]["caveats"])}
    return filled


def _pair(barrel: dict | None) -> dict | None:
    if barrel is None or barrel.get("state") != "computed":
        return None
    return {"brent": barrel["inputs"]["brent"]["shown"], "crack": barrel["crack"]["shown"]}


def placed(note: dict, latest_id: str | None, latest_barrel: dict | None, bound_barrel: dict | None,
           bound_situation: dict | None = None) -> dict:
    """The note with its prose filled from the snapshot it was written for (its barrel and, for an analysis, its
    Situation Now windows), and how it stands against the latest. A note whose snapshot is missing, not verified, has
    no complete barrel, does not hold its observation date or does not compute a window the analysis names is unbound:
    its prose is never shown as a current reading."""
    unbound = {**note, "state": "unbound", "then": None, "now": None}
    if bound_barrel is None:
        return {**unbound, "problem": "The snapshot this note was written for is not among the verified snapshots."}
    if bound_barrel.get("state") != "computed":
        return {**unbound, "problem": "The snapshot this note was written for has no complete barrel."}
    if bound_barrel.get("date") != note["observation_date"]:
        return {**unbound, "problem": "The snapshot this note was written for does not hold its observation date."}
    try:
        filled = _prose_fields(note, bound_barrel, bound_situation)
    except Unfillable as missing:
        return {**unbound, "problem": f"The snapshot this note was written for does not compute the {missing.window} "
                                      "window its analysis describes."}
    if note["snapshot_id"] == latest_id:
        return {**filled, "state": "current", "problem": None, "then": None, "now": None}
    now = _pair(latest_barrel)
    problem = None
    if latest_barrel is None:
        problem = "No latest prices are available."
    elif now is None:
        problem = f"The latest prices are withheld: {latest_barrel.get('problem') or 'no complete barrel'}"
    return {**filled, "state": "earlier", "problem": problem, "then": _pair(bound_barrel), "now": now}

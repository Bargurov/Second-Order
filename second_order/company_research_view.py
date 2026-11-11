"""The FCX company page as served (company-research-0.2): the committed research package (research/fcx: facts.json,
sources.json, key_tables.json and page.json) with its four retained documents verified on every read.

Each retained file is checked against its committed acquisition record (research/fcx/acquisition/<approval>/
outcome-<n>.json) and its sources.json entry: the record must be a complete HTTP 200 response for the same address,
retrieval time, size and SHA-256, and the file on this machine must have that size and SHA-256. A source that is not on
this machine is "missing"; one that disagrees anywhere is "changed".

Nothing that rests on an unverified source is sent:
- a published figure or passage from it carries no value, printed figure or quote, only why it is withheld;
- a computed figure is recomputed here with exact decimals (ROUND_HALF_EVEN at its stated places, as thesis_arithmetic
  rounds) and is withheld when any input is withheld or when it does not recompute;
- a page text that names a withheld figure or passage is withheld whole.

What names a figure (its name, unit, basis, location and period label) is sent even when it is withheld, so it carries
no percentage: a share or rate from a document, such as FCX's ownership of a mine, is a figure of its own record and is
shown only when that record's document is verified. A name that carries one refuses the read.

Problems are fixed text that names sources and record ids, never a value from a file. The page's prose holds no
digits but years: every number in it is a placeholder ({{record-id}}; {{record-id|signed}} with its sign, or
{{record-id|size}} without one) that the page fills from the record. Nothing here writes, fetches or calls a model, and every reply carries "provider_called": false.
"""
import ast
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from pathlib import Path

from .fuels_notes import refused_phrase
from .thesis_sources import ROOT

VIEW_VERSION = "company-research-0.2"
PAGE_VERSION = "company-page-0.2"
RESEARCH_DIR = ROOT / "research" / "fcx"
SOURCES_DIR = ROOT / "data" / "company-sources" / "fcx"
SOURCE_IDS = ("10k-2025", "10q-2026q3", "release-2026q3", "news-2026-11-04")
SOURCE_SHOWN = ("id", "title", "issuer", "form", "period_end", "date", "date_kind", "url", "host", "format", "bytes",
                "sha256", "retrieved_at", "acquisition", "terms")
SOURCE_FIELDS = set(SOURCE_SHOWN) | {"sec_accession", "sec_accession_basis", "retained", "pages", "approval_id",
                                     "attempt", "folder", "name"}
KINDS = ("published", "computed", "assumption")
BLOCK_KINDS = ("observation", "computed", "estimate", "company_reason", "reading", "note")
LINKS = ("stated", "conditional", "not_measured")
TEXT_KEYS = {"text", "title", "label", "teaser", "question", "measure", "per", "period_text", "effect_on",
             "conditions", "caption", "compare_label", "heading", "kicker", "name", "short", "place", "what",
             "reported", "note_label"}
REF_KEYS = {"record", "value", "compare"}
PLACEHOLDER = re.compile(r"\{\{([a-z0-9][a-z0-9-]*)(?:\|(signed|size))?\}\}")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
FORMS = re.compile(r"\b(?:10-K|10-Q|8-K)\b")  # document names, not figures
PRECISION = 60
MAX_TEXT = 1200
SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
PERCENT = re.compile(r"\d\s*%")
NAME_FIELDS = ("metric", "unit", "basis", "location")
VALUATION = re.compile(r"\b(?:target price|price target|fair value|valuation of|buy rating|sell rating|"
                       r"recommend(?:ation)?|overweight|underweight|upside|downside)\b", re.IGNORECASE)


class CompanyRefused(Exception):
    """The committed research cannot be served: 503 when a file is missing, 500 when one is malformed."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _strict(text: str, what: str):
    def pairs(items):
        if len({key for key, _ in items}) != len(items):
            raise ValueError("a repeated key")
        return dict(items)

    def constant(name):
        raise ValueError(f"the non-standard constant {name}")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=Decimal)
    except (ValueError, RecursionError):
        raise CompanyRefused(500, f"{what} is not strict JSON") from None


def _load(folder: Path, name: str):
    path = Path(folder) / name
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise CompanyRefused(503, f"The research file {name} is missing; nothing is served") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise CompanyRefused(500, f"The research file {name} cannot be read ({type(exc).__name__})") from None
    return _strict(text, f"The research file {name}")


def _check(ok: bool, where: str, rule: str) -> None:
    if not ok:
        raise CompanyRefused(500, f"{where}: {rule}")


# ---------------------------------------------------------------- the sources

def load_sources(research: Path) -> list[dict]:
    data = _load(research, "sources.json")
    _check(isinstance(data, dict) and isinstance(data.get("sources"), list), "sources.json", "expected a sources list")
    sources = data["sources"]
    _check(all(isinstance(item, dict) for item in sources) and [item.get("id") for item in sources] == list(SOURCE_IDS),
           "sources.json", "expected exactly the four FCX documents, in order")
    for item in sources:
        _check(set(item) == SOURCE_FIELDS, f"sources.json[{item['id']}]", "not exactly a company source entry's fields")
        for field in ("approval_id", "folder", "name"):
            _check(isinstance(item[field], str) and bool(SEGMENT.match(item[field])) and item[field] not in (".", ".."),
                   f"sources.json[{item['id']}].{field}", "expected a single file or folder name")
        _check(type(item["attempt"]) is int and item["attempt"] >= 1, f"sources.json[{item['id']}].attempt",
               "expected a whole number of at least 1")
        _check(type(item["bytes"]) is int and isinstance(item["sha256"], str) and len(item["sha256"]) == 64,
               f"sources.json[{item['id']}]", "expected a size and a SHA-256")
    return sources


def _state(name: str, detail: str) -> dict:
    return {"state": name, "detail": detail}


def verify(source: dict, research: Path, sources_root: Path) -> dict:
    """{"state": "verified" | "missing" | "changed", "detail"} for one retained document; reads only."""
    approval, attempt = source["approval_id"], source["attempt"]
    record_path = Path(research) / "acquisition" / approval / f"outcome-{attempt}.json"
    path = Path(sources_root) / source["folder"] / source["name"]
    if not record_path.is_file():
        return _state("missing", f"The acquisition record (approval {approval}, attempt {attempt}) is not in the research "
                                 "folder; the retained file is not used.")
    if not path.is_file():
        return _state("missing", f"The retained file {source['folder']}/{source['name']} is not on this machine.")
    try:
        record = _strict(record_path.read_bytes().decode("utf-8"), "The acquisition record")
    except (OSError, UnicodeDecodeError, CompanyRefused):
        record = None
    if not isinstance(record, dict):
        return _state("changed", "The acquisition record cannot be read as one strict JSON object; the retained file is "
                                 "not used.")
    expected = {"outcome": "complete", "http_status": 200, "hash_kind": "complete_response", "approval_id": approval,
                "n": attempt, "url": source["url"], "sha256": source["sha256"], "bytes": source["bytes"],
                "dispatched_at": source["retrieved_at"]}
    disagree = [field for field, value in expected.items()
                if not (type(record.get(field)) is type(value) and record.get(field) == value)]
    if disagree:
        return _state("changed", f"The acquisition record disagrees with this source on {', '.join(disagree)}; the "
                                 "retained file is not used.")
    try:
        if path.stat().st_size != source["bytes"]:
            return _state("changed", "The retained file's size differs from its acquisition record; it is not used.")
        raw = path.read_bytes()
    except OSError:
        return _state("missing", f"The retained file {source['folder']}/{source['name']} cannot be read here.")
    if len(raw) != source["bytes"] or sha256(raw).hexdigest() != source["sha256"]:
        return _state("changed", "The retained file's size or SHA-256 differs from its acquisition record; it is not "
                                 "used.")
    return _state("verified", "The retained file matches its acquisition record: address, retrieval time, size and "
                              "SHA-256.")


def refused_requests(research: Path) -> list[dict]:
    """Every committed request record whose outcome is not complete (the Bagdad detail page): shown as a request, never
    as a source."""
    found = []
    for path in sorted((Path(research) / "acquisition").glob("*/outcome-*.json")):
        try:
            record = _strict(path.read_bytes().decode("utf-8"), "An acquisition record")
        except (OSError, UnicodeDecodeError, CompanyRefused):
            continue
        if isinstance(record, dict) and record.get("outcome") != "complete":
            found.append({key: record.get(key) for key in ("approval_id", "n", "url", "outcome", "http_status")})
    return found


# ---------------------------------------------------------------- exact numbers

def text_of(value: Decimal) -> str:
    """A decimal as plain text, never in exponent form."""
    return format(value, "f")


def printed_value(display: str) -> Decimal:
    """A figure as the research records print it: "7,546", "(1,061)", "20%", "0.43%", "—" (zero)."""
    if not isinstance(display, str) or not display:
        raise ValueError("a printed figure is text")
    if display == "—":
        return Decimal(0)
    negative = display.startswith("(") and display.endswith(")")
    body = display[1:-1] if negative else display
    body = body[:-1] if body.endswith("%") else body
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", body):
        raise ValueError(f"not a printed figure: {display!r}")
    value = Decimal(body.replace(",", ""))
    return -value if negative else value


def number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("a value is a number")
    return Decimal(value)


def evaluate(formula: str, values: dict[str, Decimal]) -> Decimal:
    """+ - * / and parentheses over named inputs and numbers, exactly (60 significant digits for a division)."""
    tree = ast.parse(formula, mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ZeroDivisionError("a division by zero")
            with localcontext() as ctx:
                ctx.prec = PRECISION
                return {ast.Add: left + right, ast.Sub: left - right, ast.Mult: left * right,
                        ast.Div: left / right if right else Decimal(0)}[type(node.op)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        raise ValueError("not allowed in a formula")

    return walk(tree)


def quantize(value: Decimal, places: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------- the records

def _period_ok(period) -> bool:
    return isinstance(period, dict) and isinstance(period.get("label"), str) and isinstance(period.get("end"), str) \
        and period.get("kind") in ("quarter", "half_year", "nine_months", "year", "as_of", "outlook")


def _validate_records(facts) -> tuple[list[dict], list[dict]]:
    _check(isinstance(facts, dict) and isinstance(facts.get("records"), list) and isinstance(facts.get("passages"), list),
           "facts.json", "expected records and passages")
    seen = set()
    for record in facts["records"]:
        _check(isinstance(record, dict) and isinstance(record.get("id"), str), "facts.json", "a record without an id")
        rid = record["id"]
        _check(rid not in seen, f"facts.json[{rid}]", "a repeated id")
        seen.add(rid)
        _check(record.get("kind") in KINDS, f"facts.json[{rid}]", "an unknown kind")
        if record["kind"] == "assumption":
            _check(isinstance(record.get("statement"), str) and isinstance(record.get("used_by"), list),
                   f"facts.json[{rid}]", "an assumption needs a statement and used_by")
            _check(isinstance(record.get("rests_on"), list) and all(s in SOURCE_IDS for s in record["rests_on"]),
                   f"facts.json[{rid}].rests_on", "expected the source ids of the documents its statement describes")
            continue
        _check(_period_ok(record.get("period")) and isinstance(record.get("unit"), str) and record["unit"]
               and isinstance(record.get("basis"), str) and record["basis"], f"facts.json[{rid}]",
               "a figure needs a period, a unit and a basis")
        named = {field: record[field] for field in NAME_FIELDS if isinstance(record.get(field), str)}
        for field, text in {**named, "period.label": record["period"]["label"]}.items():
            _check(not PERCENT.search(text), f"facts.json[{rid}].{field}",
                   "what names a figure carries no percentage: a share or rate from a document is its own record")
        if record["kind"] == "published":
            _check(all(isinstance(record.get(k), str) and record[k] for k in ("source", "display", "quote"))
                   and type(record.get("page")) is int, f"facts.json[{rid}]",
                   "a published figure needs a source, a page, a printed figure and a quote")
            _check(record["source"] in SOURCE_IDS, f"facts.json[{rid}]", "an unknown source")
        else:
            _check(isinstance(record.get("formula"), str) and isinstance(record.get("inputs"), dict)
                   and type(record.get("decimals", 0)) is int, f"facts.json[{rid}]",
                   "a computed figure needs a formula, inputs and its places")
    for passage in facts["passages"]:
        _check(isinstance(passage, dict) and isinstance(passage.get("id"), str) and passage.get("source") in SOURCE_IDS
               and isinstance(passage.get("quote"), str) and type(passage.get("page")) is int, "facts.json",
               "a passage needs an id, a known source, a page and a quote")
        _check(passage["id"] not in seen, f"facts.json[{passage['id']}]", "a repeated id")
        seen.add(passage["id"])
    for record in facts["records"]:
        for name, used in (record.get("inputs") or {}).items():
            _check(used in seen and used != record["id"], f"facts.json[{record['id']}].inputs.{name}",
                   "names an unknown record")
    return facts["records"], facts["passages"]


# What a withheld record still carries: what it is, where it would come from, and why it is not shown. Everything else
# (a note, a computation's explanation, printed row and column labels, a quote, a value) rests on the document and stays
# out of the reply.
IDENTIFYING = {
    "published": ("id", "kind", "metric", "unit", "period", "basis", "source", "page", "printed_page", "location"),
    "computed": ("id", "kind", "metric", "unit", "period", "basis", "formula", "inputs", "decimals", "assumptions"),
}

SHORT_NAMES = {"10k-2025": "the 2025 Form 10-K", "10q-2026q3": "the third-quarter 2026 Form 10-Q",
               "release-2026q3": "the results release of 27 October 2026",
               "news-2026-11-04": "the Bagdad release of 4 November 2026"}


def _names(ids) -> str:
    names = [SHORT_NAMES[sid] for sid in sorted(ids)]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _withheld_text(sources: dict, sid: str) -> str:
    return f"Not shown: it rests on {SHORT_NAMES[sid]}, which is {sources[sid]['state']} on this machine."


def _unverified_text(subject: str, bad: set) -> str:
    verb = "is" if len(bad) == 1 else "are"
    return f"Not shown: {subject} rests on {_names(bad)}, which {verb} not verified on this machine."


def resolve_records(records: list[dict], passages: list[dict], sources: dict) -> tuple[dict, dict]:
    """Every record and passage as sent: available with its value, or withheld with a fixed reason and no value."""
    by_id = {record["id"]: record for record in records}
    out: dict[str, dict] = {}

    def identity(record: dict) -> dict:
        return {key: record[key] for key in IDENTIFYING[record["kind"]] if key in record}

    def published(record: dict) -> dict:
        shown = {key: record[key] for key in ("id", "kind", "metric", "unit", "period", "basis", "source", "page",
                                              "printed_page", "location", "row", "column", "note") if key in record}
        shown["rests_on"] = [record["source"]]
        withheld = {**identity(record), "rests_on": [record["source"]], "state": "withheld", "value": None,
                    "display": None, "quote": None}
        state = sources[record["source"]]["state"]
        if state != "verified":
            return {**withheld, "problem": _withheld_text(sources, record["source"])}
        try:
            value = number(record["value"])
            ok = printed_value(record["display"]) == value
        except (ValueError, InvalidOperation):
            ok = False
        if not ok:
            return {**withheld, "problem": f"Not shown: the printed figure of {record['id']} does not read as its "
                                           "value."}
        return {**shown, "state": "available", "problem": None, "value": text_of(value), "display": record["display"],
                "quote": record["quote"]}

    def computed(record: dict, trail: tuple) -> dict:
        shown = {key: record[key] for key in ("id", "kind", "metric", "unit", "period", "basis", "formula", "inputs",
                                              "note", "basis_mix", "period_mix", "unit_mix", "assumptions")
                 if key in record}
        shown["decimals"] = record.get("decimals", 0)
        inputs = {name: resolve(used, trail + (record["id"],)) for name, used in record["inputs"].items()}
        shown["rests_on"] = sorted({sid for item in inputs.values() for sid in item.get("rests_on", [])})
        withheld = {**identity(record), "decimals": shown["decimals"], "rests_on": shown["rests_on"],
                    "state": "withheld", "value": None}
        blocked = sorted({used for name, used in record["inputs"].items() if inputs[name]["state"] != "available"})
        if blocked:
            bad = {sid for sid in shown["rests_on"] if sources[sid]["state"] != "verified"}
            return {**withheld, "problem": _unverified_text("it", bad) if bad else
                    f"Not shown: it uses {', '.join(blocked)}, which is not shown."}
        try:
            result = quantize(evaluate(record["formula"], {name: Decimal(item["value"]) for name, item in
                                                           inputs.items()}), shown["decimals"])
            stated = number(record["value"])
            ok = result == quantize(stated, shown["decimals"])
        except (ValueError, KeyError, ZeroDivisionError, InvalidOperation, SyntaxError):
            ok = False
        if not ok:
            return {**withheld, "problem": f"Not shown: {record['id']} does not recompute from its inputs."}
        return {**shown, "state": "available", "problem": None, "value": text_of(stated)}

    def resolve(rid: str, trail: tuple = ()) -> dict:
        if rid in out:
            return out[rid]
        if rid in trail:
            raise CompanyRefused(500, f"facts.json[{rid}]: a computed figure depends on itself")
        record = by_id.get(rid)
        if record is None:  # a passage named as an input is not a figure
            raise CompanyRefused(500, f"facts.json: {rid} is not a figure")
        if record["kind"] == "published":
            out[rid] = published(record)
        elif record["kind"] == "computed":
            out[rid] = computed(record, trail)
        else:  # an assumption: its statement is withheld when a document it describes is not verified
            bad = {sid for sid in record["rests_on"] if sources[sid]["state"] != "verified"}
            out[rid] = {"id": rid, "kind": "assumption", "used_by": record["used_by"], "rests_on": record["rests_on"],
                        "statement": None if bad else record["statement"], "state": "withheld" if bad else "available",
                        "problem": _unverified_text("this assumption", bad) if bad else None}
        return out[rid]

    for record in records:
        resolve(record["id"])
    sent = {record["id"]: out[record["id"]] for record in records}
    quotes = {}
    for passage in passages:
        shown = {key: passage[key] for key in ("id", "source", "page", "printed_page", "location", "topic")
                 if key in passage}
        if sources[passage["source"]]["state"] == "verified":
            quotes[passage["id"]] = {**shown, "state": "available", "problem": None, "quote": passage["quote"]}
        else:
            quotes[passage["id"]] = {**shown, "state": "withheld", "quote": None,
                                     "problem": _withheld_text(sources, passage["source"])}
    return sent, quotes


# ---------------------------------------------------------------- the page texts

def prose(value, where: str, placeholders: bool) -> None:
    _check(isinstance(value, str) and 0 < len(value) <= MAX_TEXT, where, "expected non-empty text of limited length")
    rest = PLACEHOLDER.sub("", value) if placeholders else value
    _check("{" not in rest and "}" not in rest, where, "braces may only form a record placeholder")
    _check(not re.search(r"\d", YEAR.sub("", FORMS.sub("", rest))), where,
           "numbers belong to the records: no digits except years and form names")
    _check(not refused_phrase(value), where, "causal and forecast phrasing is not allowed in the page's own words")
    _check(not VALUATION.search(value), where, "no valuation, target price, rating or recommendation")


def segments(text: str) -> list[dict]:
    out, at = [], 0
    for match in PLACEHOLDER.finditer(text):
        if match.start() > at:
            out.append({"text": text[at:match.start()]})
        out.append({"ref": match.group(1), "mode": match.group(2)})
        at = match.end()
    if at < len(text):
        out.append({"text": text[at:]})
    return out


def resolve_page(page, records: dict, passages: dict, sources: dict) -> dict:
    """page.json checked and resolved: every text block in segments, with the state of what it names."""
    _check(isinstance(page, dict) and page.get("page_version") == PAGE_VERSION, "page.json",
           f"expected page_version {PAGE_VERSION}")

    def ref(value, where):
        _check(isinstance(value, str) and value in records, where, "names an unknown record")

    def block(item: dict, where: str) -> dict:
        _check(item.get("kind") in BLOCK_KINDS, f"{where}.kind", f"expected one of {', '.join(BLOCK_KINDS)}")
        prose(item.get("text"), f"{where}.text", placeholders=True)
        cited = item.get("passages", [])
        _check(isinstance(cited, list) and all(isinstance(p, str) and p in passages for p in cited),
               f"{where}.passages", "names an unknown passage")
        parts = segments(item["text"])
        refs = [part["ref"] for part in parts if "ref" in part]
        for name in refs:
            ref(name, f"{where}.text")
        blocked = sorted({name for name in refs if records[name]["state"] != "available"}
                         | {name for name in cited if passages[name]["state"] != "available"})
        bad = {sid for name in refs for sid in records[name].get("rests_on", [])
               if sources[sid]["state"] != "verified"} | {passages[name]["source"] for name in cited
                                                          if passages[name]["state"] != "available"}
        extra = {key: walk(value, f"{where}.{key}") for key, value in item.items()
                 if key not in ("kind", "text", "passages")}
        # A withheld line sends no words, only what it names: its words may say what the unverified document says.
        return {**extra, "kind": item["kind"], "segments": None if blocked else parts, "refs": refs, "passages": cited,
                "state": "withheld" if blocked else "available",
                "problem": None if not blocked else _unverified_text("this line", bad) if bad else
                f"Not shown: this line uses {', '.join(blocked)}, which is not shown."}

    def walk(node, where: str):
        if isinstance(node, dict):
            if "kind" in node and "text" in node:
                return block(node, where)
            out = {}
            for key, value in node.items():
                here = f"{where}.{key}"
                if key in TEXT_KEYS:
                    prose(value, here, placeholders=False)
                    out[key] = value
                elif key in REF_KEYS:
                    if value is not None:
                        ref(value, here)
                    out[key] = value
                elif key == "ids":
                    _check(isinstance(value, list), here, "expected a list")
                    for at, item in enumerate(value):
                        if item is not None:
                            ref(item, f"{here}[{at}]")
                    out[key] = value
                elif key == "passages":
                    _check(isinstance(value, list) and all(isinstance(p, str) and p in passages for p in value), here,
                           "names an unknown passage")
                    out[key] = value
                elif key == "link":
                    _check(value in LINKS, here, f"expected one of {', '.join(LINKS)}")
                    out[key] = value
                else:
                    out[key] = walk(value, here)
            return out
        if isinstance(node, list):
            return [walk(item, f"{where}[{at}]") for at, item in enumerate(node)]
        if isinstance(node, (Decimal, bool, int, float)):
            raise CompanyRefused(500, f"{where}: page.json holds no numbers; figures come from the records")
        return node

    return walk({key: value for key, value in page.items() if key != "page_version"}, "page.json")


# ---------------------------------------------------------------- the view

def facts_passages(research: Path = RESEARCH_DIR) -> list[dict]:
    """The raw passages of facts.json, validated as resolved() validates them. Raises CompanyRefused. Reads only."""
    return _validate_records(_load(Path(research), "facts.json"))[1]


def resolved(research: Path = RESEARCH_DIR, sources_root: Path = SOURCES_DIR) -> tuple[dict, dict, dict]:
    """The sources with their states, and every record and passage as sent, verified now. Reads only."""
    research, sources_root = Path(research), Path(sources_root)
    entries = load_sources(research)
    states = {item["id"]: verify(item, research, sources_root) for item in entries}
    sources = {item["id"]: {**{key: item[key] for key in SOURCE_SHOWN}, **states[item["id"]]} for item in entries}
    records, quotes = resolve_records(*_validate_records(_load(research, "facts.json")), sources)
    return sources, records, quotes


def view(research: Path = RESEARCH_DIR, sources_root: Path = SOURCES_DIR) -> dict:
    """The whole read (see the module docstring). Reads only."""
    research = Path(research)
    sources, records, quotes = resolved(research, sources_root)
    page = resolve_page(_load(research, "page.json"), records, quotes, sources)
    verified = sum(1 for item in sources.values() if item["state"] == "verified")
    return {
        "view_version": VIEW_VERSION,
        "provider_called": False,
        "sources": list(sources.values()),
        "verified": verified,
        "requests": refused_requests(research),
        "records": records,
        "passages": quotes,
        "page": page,
    }

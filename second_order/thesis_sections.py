"""Strict checks of a committed thesis version's sections (thesis-0.1): the balance tables, where the view differs,
reasons, risks, conditions, exposure, the view log, the price record and the plain notes, plus the statement shape and
record helpers they share with thesis_schema, which checks the file's top level, sources, figures and passages.

Every check reads the version file's content only; no retained source is read here (thesis_view does that on read).
Every field is required and none is defaulted. Author text is held to the figures and passages its element cites
(thesis_rules.held_to) and to that element's computed outputs, each computed here as fixed code computes it for display
(thesis_arithmetic, ROUND_HALF_EVEN): a computed balance row's gap and weeks of demand, a reason's or risk's change in
percent (one decimal), a condition's threshold (as written and grouped), and a computed exposure row's cost per unit
(whole dollars) and share of the unit price (one decimal, from that cost). Text that cites nothing states no figures,
and plain notes and log entries state none at all.

A computed balance gap draws every figure of its table from one source, basis, scenario and unit, so nothing is
converted or mixed; a row's figures are of its year, and a projection row's carry a scenario. A reason or risk
compares a latest figure of its evidence with a previous one of the same measure, unit, basis and scenario: from two
editions of one series (two sources whose edition text differs) with a strictly later edition date, either one year and
period revised (revision) or a later year (period), or (ruling R12) from one edition, a later year only (period; a
revision within one edition would compare a figure with itself); a period comparison compares periods of one kind, and
a previous value of zero is refused, since no change can be computed from it. The price record's series is author text
held to its two figures. Element ids (tables, differs, reasons, risks, conditions) are distinct, and every listed
source, figure and passage is used by some element. Raises thesis_rules.ThesisRefused (500).
"""
from datetime import date
from decimal import Decimal
import re

from . import policy_research
from .thesis_arithmetic import balance, change_pct, decimal_of, display, per_unit_cost, share_pct
from .thesis_rules import (BANNED, PRICE_DIRECTION, STATEMENT_STATUSES, author_text, check, free_text, held_to,
                           invalid, no_figures)

ID = policy_research.ID
# ASCII digits only: \d also matches other scripts' digits, which as text sort after "2" (a year's order is the only
# order a measure within one edition has, ruling R12). Wherever years are ordered they are compared as integers.
YEAR = re.compile(r"[0-9]{4}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")  # date.fromisoformat, which day() also applies, reads ASCII digits only.
# A figure's period within its year: a month as the Pink Sheet prints it, a quarter, or a day.
PERIOD = re.compile(r"[0-9]{4}(?:M(?:0[1-9]|1[0-2])|Q[1-4]|-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))")
MAX_TITLE, MAX_LABEL, MAX_PLAIN, MAX_COMPANY = 120, 120, 300, 200

GAPS = ("computed", "not_computed")
ROW_KINDS = ("historical", "projection")
COMPARES = ("revision", "period")
DIRECTIONS = ("higher", "lower")
COMPARATORS = ("below", "above")
SIDES = ("producer", "consumer")
AMOUNT_KINDS = ("stated", "computed")
LOG_KINDS = ("opened", "status", "view", "confidence", "note")
PRICE_UNITS = ("usd_per_tonne", "usd_cents_per_lb")  # R18: the price record's units; the cost arithmetic stays tonne.
PLAIN_KEYS = ("view", "balance", "differs", "reasons", "risks", "conditions", "exposure", "log", "price")
NOTHING = "cites no figure or passage, so nothing on it could be checked"  # R15
ATTRIBUTION_WORDS = ("forecast", "forecasts")  # The one claim word a label may use: naming another's forecast.

STATEMENT_FIELDS = {"status", "text", "cites"}
TABLE_FIELDS = {"id", "title", "gap", "why_not", "rows"}
ROW_FIELDS = {"year", "kind", "demand_total", "supply_total", "lines"}
LINE_FIELDS = {"label", "figure"}
DIFFERS_FIELDS = {"id", "about", "others", "differs"}
OTHER_FIELDS = {"cite", "label"}
CLAIM_FIELDS = {"id", "title", "statement", "plain", "measure"}
CONDITION_FIELDS = {"id", "text", "figure", "comparator", "threshold"}
MOVER_FIELDS = {"company", "moves", "through", "cites"}
MOVED_FIELDS = {"company", "side", "how", "amount"}
STATED_FIELDS = {"kind", "figure"}
COMPUTED_FIELDS = {"kind", "per_unit", "price", "unit_price"}
LOG_FIELDS = {"date", "kind", "text", "refs"}
PRICE_FIELDS = {"series", "opening", "latest"}


# ---------------------------------------------------------------- record helpers shared with thesis_schema

def fields(value: object, expected: set[str], where: str) -> dict:
    check(isinstance(value, dict) and set(value) == expected, where, f"expected exactly the fields {sorted(expected)}")
    return value


def items(value: object, where: str, minimum: int = 0, maximum: int | None = None) -> list:
    check(isinstance(value, list) and len(value) >= minimum and (maximum is None or len(value) <= maximum), where,
          f"expected a list of {minimum} to {maximum} entries" if maximum is not None
          else f"expected a list of at least {minimum}")
    return value


def ident(value: object, where: str, taken) -> str:
    check(isinstance(value, str) and bool(ID.fullmatch(value)) and value not in taken, where,
          "expected a distinct lower-case id")
    return value


def day(value: object, where: str) -> str:
    try:
        valid = isinstance(value, str) and bool(DAY.fullmatch(value)) and bool(date.fromisoformat(value))
    except ValueError:
        valid = False
    check(valid, where, "expected a YYYY-MM-DD date")
    return value


def number(value: object, where: str) -> Decimal:
    try:
        return decimal_of(value)
    except ValueError:
        raise invalid(where, "expected a plain decimal written as text") from None


def places(value: Decimal) -> int:
    return max(0, -value.as_tuple().exponent)


def shown(figure: dict) -> str:
    """What a figure lets text state: its printed and plain value, year and period."""
    return " ".join(part for part in (figure["as_shown"], figure["value"], figure["year"], figure["period"]) if part)


def allowed(cited: list[dict]) -> str:
    """The figures that text citing these figures and passages may state (a passage's whole quote)."""
    return " ".join(shown(item) if "value" in item else item["locator"]["quote"] for item in cited)


def period_kind(period: str | None) -> str:
    return "year" if period is None else {"M": "month", "Q": "quarter"}.get(period[4], "day")


class _Elements:
    """A version's figures, passages and sources, and which of them its elements use."""

    def __init__(self, figures: dict, passages: dict, sources: dict):
        self.figures, self.passages, self.sources, self.used = figures, passages, sources, set()

    def figure(self, value: object, where: str, unit: str | None = None) -> dict:
        check(isinstance(value, str) and value in self.figures, where, "names no listed figure")
        figure = self.figures[value]
        check(unit is None or figure["unit"] == unit, where, f"expected a figure in {unit}")
        self.used.add(value)
        return figure

    def cites(self, value: object, where: str, minimum: int) -> list[dict]:
        cited = items(value, where, minimum)
        check(all(isinstance(name, str) and (name in self.figures or name in self.passages) for name in cited), where,
              "names no listed figure or passage")
        check(len(set(cited)) == len(cited), where, "names one figure or passage twice")
        self.used.update(cited)
        return [self.figures[name] if name in self.figures else self.passages[name] for name in cited]

    def statement(self, value: object, where: str, computed: str = "") -> dict:
        """{status, text, cites}: not_stated cites nothing, the others at least one figure or passage; the text is
        held to what it cites and to ``computed``, the element's computed outputs."""
        fields(value, STATEMENT_FIELDS, where)
        check(isinstance(value["status"], str) and value["status"] in STATEMENT_STATUSES, f"{where}.status",
              f"expected one of {list(STATEMENT_STATUSES)}")
        silent = value["status"] == "not_stated"
        cited = self.cites(value["cites"], f"{where}.cites", 0 if silent else 1)
        check(not (silent and cited), f"{where}.cites", "a statement the sources do not make cites nothing")
        held_to(author_text(value["text"], f"{where}.text"), f"{allowed(cited)} {computed}", f"{where}.text")
        return value


def statement(value: object, where: str, figures: dict, passages: dict) -> dict:
    """One statement, checked against the version's figures and passages."""
    return _Elements(figures, passages, {}).statement(value, where)


def _attribution(value: object, where: str) -> str:
    """A label naming whose expectation a cited figure or passage is ("Synthetic World Bank forecast"): author text
    that may say "forecast", since it names another institution's, but no other claim word and no price direction."""
    text = free_text(value, where, MAX_LABEL)
    for found in BANNED.finditer(text):
        check(found.group(0).lower() in ATTRIBUTION_WORDS, where,
              f"uses {found.group(0)!r}, which belongs only to the list of claims not made")
    found = PRICE_DIRECTION.search(text)
    check(found is None, where, f"uses {found.group(0)!r}, which states a view on a price's direction" if found else "")
    return text


# ---------------------------------------------------------------- the sections

def _row(row: object, where: str, elements: _Elements, previous: str | None) -> list[str]:
    fields(row, ROW_FIELDS, where)
    check(isinstance(row["year"], str) and bool(YEAR.fullmatch(row["year"])), f"{where}.year",
          "expected a four-digit year")
    check(previous is None or int(row["year"]) > int(previous), f"{where}.year", "expected years that increase")
    check(row["kind"] in ROW_KINDS, f"{where}.kind", f"expected one of {list(ROW_KINDS)}")
    demand = elements.figure(row["demand_total"], f"{where}.demand_total")
    check(decimal_of(demand["value"]) > 0, f"{where}.demand_total", "expected demand greater than 0")
    elements.figure(row["supply_total"], f"{where}.supply_total")
    names = [row["demand_total"], row["supply_total"]]
    for index, line in enumerate(items(row["lines"], f"{where}.lines")):
        place = f"{where}.lines[{index}]"
        fields(line, LINE_FIELDS, place)
        figure = elements.figure(line["figure"], f"{place}.figure")
        held_to(author_text(line["label"], f"{place}.label", MAX_LABEL), shown(figure), f"{place}.label")
        names.append(line["figure"])
    check(len(set(names)) == len(names), where, "names one figure twice")
    for name in names:
        figure = elements.figures[name]
        check(figure["year"] == row["year"], where, f"figure {name} is not of the row's year")
        check(row["kind"] == "historical" or figure["scenario"] is not None, where,
              f"a projection row's figures need a scenario; figure {name} has none")
    return names


def _balance(value: object, elements: _Elements, taken: set) -> None:
    for number_, table in enumerate(items(fields(value, {"tables"}, "balance")["tables"], "balance.tables", 1)):
        where = f"balance.tables[{number_}]"
        fields(table, TABLE_FIELDS, where)
        taken.add(ident(table["id"], f"{where}.id", taken))
        where = f"balance.tables[{table['id']}]"
        check(table["gap"] in GAPS, f"{where}.gap", f"expected one of {list(GAPS)}")
        rows, names = items(table["rows"], f"{where}.rows", 1), []
        for index, row in enumerate(rows):
            names += _row(row, f"{where}.rows[{index}]", elements, rows[index - 1]["year"] if index else None)
        figures = [elements.figures[name] for name in names]
        outputs = []
        if table["gap"] == "computed":
            for key in ("source", "basis", "scenario", "unit"):
                found = {figure[key] for figure in figures}
                check(len(found) == 1, where,
                      f"a computed gap draws every figure from one {key}; this table's figures have {len(found)}")
            check(table["why_not"] is None, f"{where}.why_not", "a computed table gives no reason for not computing")
            for row in rows:
                gap = balance(decimal_of(elements.figures[row["supply_total"]]["value"]),
                              decimal_of(elements.figures[row["demand_total"]]["value"]))
                outputs += [display(gap["gap"], places(gap["gap"])), display(gap["weeks"], 1)]
        text = f"{allowed(figures)} {' '.join(outputs)}"
        if table["gap"] == "not_computed":
            held_to(author_text(table["why_not"], f"{where}.why_not"), text, f"{where}.why_not")
        held_to(author_text(table["title"], f"{where}.title", MAX_TITLE), text, f"{where}.title")


def _differs(values: object, elements: _Elements, taken: set) -> None:
    for number_, item in enumerate(items(values, "differs", 1)):
        where = f"differs[{number_}]"
        fields(item, DIFFERS_FIELDS, where)
        taken.add(ident(item["id"], f"{where}.id", taken))
        where = f"differs[{item['id']}]"
        elements.statement(item["about"], f"{where}.about")
        cites = []
        for index, other in enumerate(items(item["others"], f"{where}.others", 1)):
            place = f"{where}.others[{index}]"
            fields(other, OTHER_FIELDS, place)
            cited = elements.cites([other["cite"]], f"{place}.cite", 1)
            held_to(_attribution(other["label"], f"{place}.label"), allowed(cited), f"{place}.label")
            cites.append(other["cite"])
        check(len(set(cites)) == len(cites), f"{where}.others", "names one figure or passage twice")
        check(type(item["differs"]) is bool, f"{where}.differs", "expected true or false")


def _measure(value: object, where: str, elements: _Elements, direction: str) -> str:
    """A reason's or risk's latest and previous figures of one measure: from two editions of one series (two sources
    whose edition text differs), or (ruling R12) two years of one edition; a revision keeps one year and period, a
    period comparison one kind of period. Returns its change in percent as displayed."""
    measure = fields(value, {"latest", "previous", "compare", direction, "material_change_pct"}, where)
    latest = elements.figure(measure["latest"], f"{where}.latest")
    previous = elements.figure(measure["previous"], f"{where}.previous")
    for key in ("measure", "unit", "basis", "scenario"):
        check(latest[key] == previous[key], where, f"the latest and previous figures differ in {key}")
    check(measure["latest"] != measure["previous"], where, "names one figure twice")
    check(measure["compare"] in COMPARES, f"{where}.compare", f"expected one of {list(COMPARES)}")
    check(latest["year"] is not None and previous["year"] is not None, where, "both figures need a year")
    later, earlier = int(latest["year"]), int(previous["year"])  # Ordered as integers, never as text.
    if latest["source"] == previous["source"]:  # R12: a revision within one edition would compare a figure with itself.
        check(measure["compare"] == "period" and later > earlier, f"{where}.compare",
              "two figures from one edition compare a later year with an earlier one (period), never one year revised")
    else:
        newer, older = elements.sources[latest["source"]], elements.sources[previous["source"]]
        check(newer["series"] == older["series"], where, "the latest and previous figures come from different series")
        check(newer["edition"] != older["edition"], where,
              "the latest and previous figures come from two sources of one edition (the same edition text), so they "
              "do not compare two editions")
        check(newer["edition_date"] > older["edition_date"], where,
              "the latest figure must come from a later edition of the series than the previous figure")
        if measure["compare"] == "revision":
            check(later == earlier and latest["period"] == previous["period"], f"{where}.compare",
                  "a revision compares one year, and the same period within it, in two editions")
        else:
            check(later > earlier, f"{where}.compare", "a period comparison needs a later year in the later edition")
    check(measure["compare"] == "revision" or period_kind(latest["period"]) == period_kind(previous["period"]),
          f"{where}.compare", "a period comparison compares periods of one kind (years, quarters, months or days)")
    check(measure[direction] in DIRECTIONS, f"{where}.{direction}", f"expected one of {list(DIRECTIONS)}")
    check(number(measure["material_change_pct"], f"{where}.material_change_pct") > 0, f"{where}.material_change_pct",
          "expected a change greater than 0")
    try:
        change = change_pct(decimal_of(previous["value"]), decimal_of(latest["value"]))
    except ZeroDivisionError:
        raise invalid(f"{where}.previous", "the previous value is 0, so no change can be computed from it") from None
    return display(change, 1)


def _claims(values: object, name: str, elements: _Elements, taken: set, direction: str, minimum: int,
            maximum: int | None, untracked: bool) -> list[str]:
    """Reasons (``supports_when``) or risks (``grows_when``; ``untracked`` allows a null measure). Returns the ids."""
    ids = []
    for number_, item in enumerate(items(values, name, minimum, maximum)):
        where = f"{name}[{number_}]"
        fields(item, CLAIM_FIELDS, where)
        taken.add(ident(item["id"], f"{where}.id", taken))
        where = f"{name}[{item['id']}]"
        change, measured = "", []
        if not (untracked and item["measure"] is None):
            change = _measure(item["measure"], f"{where}.measure", elements, direction)
            measured = [elements.figures[item["measure"]["latest"]], elements.figures[item["measure"]["previous"]]]
        stated = elements.statement(item["statement"], f"{where}.statement", change)
        cited = [elements.figures.get(cite) or elements.passages[cite] for cite in stated["cites"]]
        # Ruling R15: an element must cite something, or its "checked" label would be vacuously true.
        check(bool(cited or measured), where, NOTHING)
        held_to(author_text(item["title"], f"{where}.title", MAX_TITLE), f"{allowed(cited + measured)} {change}",
                f"{where}.title")
        no_figures(author_text(item["plain"], f"{where}.plain", MAX_PLAIN), f"{where}.plain")
        ids.append(item["id"])
    return ids


def _conditions(values: object, elements: _Elements, taken: set) -> None:
    for number_, item in enumerate(items(values, "conditions", 1)):
        where = f"conditions[{number_}]"
        fields(item, CONDITION_FIELDS, where)
        taken.add(ident(item["id"], f"{where}.id", taken))
        where = f"conditions[{item['id']}]"
        figure = elements.figure(item["figure"], f"{where}.figure")
        check(item["comparator"] in COMPARATORS, f"{where}.comparator", f"expected one of {list(COMPARATORS)}")
        threshold = number(item["threshold"], f"{where}.threshold")
        held_to(author_text(item["text"], f"{where}.text"),
                f"{shown(figure)} {item['threshold']} {display(threshold, places(threshold))}", f"{where}.text")


def _amount(value: object, where: str, elements: _Elements) -> str:
    """A moved entry's amount; returns its computed outputs (cost per unit, share of the unit price) as displayed."""
    kind = value.get("kind") if isinstance(value, dict) else None
    if isinstance(value, dict) and "kind" in value:
        check(kind in AMOUNT_KINDS, f"{where}.kind", f"expected one of {list(AMOUNT_KINDS)}")
    fields(value, STATED_FIELDS if kind == "stated" else COMPUTED_FIELDS, where)
    if kind == "stated":
        elements.figure(value["figure"], f"{where}.figure")
        return ""
    per_unit = decimal_of(elements.figure(value["per_unit"], f"{where}.per_unit", "kg_per_unit")["value"])
    price = decimal_of(elements.figure(value["price"], f"{where}.price", "usd_per_tonne")["value"])
    check(per_unit > 0 and price > 0, where, "expected an amount per unit and a price greater than 0")
    cost = per_unit_cost(per_unit, price)
    outputs = [display(cost, 0)]
    if value["unit_price"] is not None:
        unit_price = decimal_of(elements.figure(value["unit_price"], f"{where}.unit_price", "usd")["value"])
        check(unit_price > 0, f"{where}.unit_price", "expected a unit price greater than 0")
        outputs.append(display(share_pct(cost, unit_price), 1))
    return " ".join(outputs)


def _exposure(value: object, elements: _Elements, reasons: list[str]) -> None:
    exposure = fields(value, {"movers", "moved"}, "exposure")
    for number_, mover in enumerate(items(exposure["movers"], "exposure.movers", 1)):
        where = f"exposure.movers[{number_}]"
        fields(mover, MOVER_FIELDS, where)
        free_text(mover["company"], f"{where}.company", MAX_COMPANY)
        check(mover["moves"] in reasons, f"{where}.moves", "names no reason")
        cited = elements.cites(mover["cites"], f"{where}.cites", 1)
        held_to(author_text(mover["through"], f"{where}.through"), allowed(cited), f"{where}.through")
    for number_, moved in enumerate(items(exposure["moved"], "exposure.moved", 1)):
        where = f"exposure.moved[{number_}]"
        fields(moved, MOVED_FIELDS, where)
        free_text(moved["company"], f"{where}.company", MAX_COMPANY)
        check(moved["side"] in SIDES, f"{where}.side", f"expected one of {list(SIDES)}")
        outputs = _amount(moved["amount"], f"{where}.amount", elements)
        elements.statement(moved["how"], f"{where}.how", outputs)


def _log(raw: dict, claims: list[str]) -> None:
    previous = None
    for number_, entry in enumerate(items(raw["log"], "log", 1)):
        where = f"log[{number_}]"
        fields(entry, LOG_FIELDS, where)
        when = day(entry["date"], f"{where}.date")
        check(entry["kind"] in LOG_KINDS, f"{where}.kind", f"expected one of {list(LOG_KINDS)}")
        check((entry["kind"] == "opened") == (number_ == 0), f"{where}.kind",
              "the first entry, and only the first, records the opening")
        check(number_ > 0 or when == raw["opened_on"], f"{where}.date",
              "the opening is dated the day the thesis opened")
        check(previous is None or when >= previous, f"{where}.date", "expected dates that do not decrease")
        check(when <= raw["prepared_on"], f"{where}.date", "is after the day this version was prepared")
        no_figures(author_text(entry["text"], f"{where}.text"), f"{where}.text")
        refs = items(entry["refs"], f"{where}.refs", 1 if entry["kind"] == "status" else 0)
        check(all(isinstance(ref, str) and ref in claims for ref in refs) and len(set(refs)) == len(refs),
              f"{where}.refs", "expected distinct ids of reasons or risks (a status entry names at least one)")
        previous = when


def _price_record(value: object, elements: _Elements) -> None:
    record = fields(value, PRICE_FIELDS, "price_record")
    opening = elements.figure(record["opening"], "price_record.opening")
    latest = elements.figure(record["latest"], "price_record.latest")
    # The series is the author's heading for the record: scanned like other author text, its figures held to the two.
    held_to(author_text(record["series"], "price_record.series", 200), allowed([opening, latest]),
            "price_record.series")
    for place, found in (("opening", opening), ("latest", latest)):  # Ruling R18: no conversion, so one unit only.
        check(found["unit"] in PRICE_UNITS, f"price_record.{place}", f"expected a figure in one of {list(PRICE_UNITS)}")
    check(opening["unit"] == latest["unit"], "price_record",
          f"the opening is in {opening['unit']} and the latest in {latest['unit']}; both must be in one unit")
    check(opening["source"] == latest["source"], "price_record", "the opening and latest prices come from one source")
    check(opening["year"] is not None and latest["year"] is not None and
          period_kind(opening["period"]) == period_kind(latest["period"]), "price_record",
          "the opening and latest prices need a year and periods of one kind")
    check((int(opening["year"]), opening["period"] or "") <= (int(latest["year"]), latest["period"] or ""),
          "price_record", "the opening price's period is after the latest's")


def _plain(value: object) -> None:
    plain = fields(value, set(PLAIN_KEYS), "plain")
    for key in PLAIN_KEYS:
        no_figures(author_text(plain[key], f"plain.{key}", MAX_PLAIN), f"plain.{key}")


def _all_used(elements: _Elements) -> None:
    for kind, listed in (("figures", elements.figures), ("passages", elements.passages)):
        unused = [name for name in listed if name not in elements.used]
        check(not unused, kind, f"lists {kind} that no element uses: {unused}")
    drawn = {item["source"] for item in [*elements.figures.values(), *elements.passages.values()]}
    idle = [name for name in elements.sources if name not in drawn]
    check(not idle, "sources", f"lists sources that no figure or passage comes from: {idle}")


def check_sections(raw: dict, figures: dict, passages: dict, sources: dict) -> None:
    """Check a version's sections against its figures, passages and sources (each by id), all of which, with the top
    level and the view, thesis_schema has already checked. Raises ThesisRefused (500)."""
    elements = _Elements(figures, passages, sources)
    elements.used.update(raw["view"]["cites"])  # The view, checked by thesis_schema, uses what it cites.
    taken = set()
    _balance(raw["balance"], elements, taken)
    _differs(raw["differs"], elements, taken)
    reasons = _claims(raw["reasons"], "reasons", elements, taken, "supports_when", 3, 5, untracked=False)
    risks = _claims(raw["risks"], "risks", elements, taken, "grows_when", 1, None, untracked=True)
    _conditions(raw["conditions"], elements, taken)
    _exposure(raw["exposure"], elements, reasons)
    _log(raw, reasons + risks)
    _price_record(raw["price_record"], elements)
    _plain(raw["plain"])
    _all_used(elements)

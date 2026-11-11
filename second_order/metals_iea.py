"""Reader for two sheets of the retained IEA Critical Minerals Dataset 2026 workbook (metals-iea-0.1).

It reads no file: a later step verifies the workbook and passes the cells of the demand and supply sheets in, as
{cell: text} (what thesis_sources.content returns; number cells are thesis_workbook.Number). The layout is checked cell
by cell and any mismatch refuses the whole IEA part. Every figure is the workbook's own number, shown as its shortest
round-trip decimal, or a share of the workbook's printed total; nothing is curated.
"""
from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
import math
import re

from second_order.thesis_workbook import Number

ENGINE = "metals-iea-0.1"
DEMAND_SHEET = "1 Total demand for key minerals"
SUPPLY_SHEET = "2 Total supply for key minerals"
DEMAND_TITLE = "Demand for key energy transition minerals (kt)"
SUPPLY_TITLE = "Total supply for key energy transition minerals, base case (kt)"
SCENARIOS = [("cps", "D", "Current Policies scenario"), ("steps", "J", "Stated Policies scenario"),
             ("hd", "P", "High Demand Scenario")]
FORECAST_YEARS = ["2030", "2035", "2040", "2045", "2050"]
SUPPLY_YEARS = ["2025", "2030", "2035", "2040"]
SHARE_LABEL, TOTAL_DEMAND, TOP3, REST = "Share of energy technologies in total demand", "Total demand", "Top 3 share", \
    "Rest of world"
MINERALS = {
    "copper": ("Copper", "Copper - Mining", "Copper - Refining", "copper"),
    "cobalt": ("Cobalt", "Cobalt - Mining", "Cobalt - Refining", "cobalt"),
    "lithium": ("Lithium", "Lithium - Mining", "Lithium - Refining", "lithium"),
    "nickel": ("Nickel", "Nickel - Mining", "Nickel - Refining", "nickel"),
    "magnet-rare-earths": ("Magnet rare earth elements", "Magnet rare earth elements - Mining",
                           "Magnet rare earth elements - Refining", "rare-earths"),
    "graphite": ("Graphite (all grades: natural and synthetic)", "Graphite - Mining (natural)",
                 "Graphite - Battery grade", "graphite-natural"),
}
SCOPE_NOTES = {
    "magnet-rare-earths": "The IEA counts magnet rare earth elements, and USGS counts all rare earths. They are "
                          "different scopes, never compared.",
    "graphite": "IEA demand covers all grades; its first supply block is natural mining and its second is battery "
                "grade.",
    "lithium": "The IEA states lithium content, as its note says.",
}
PLAIN = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
A_CELL = re.compile(r"^A(\d+)$")


class IeaRefused(ValueError):
    """The cells are not the IEA workbook layout this reader understands. `place` is "sheet!cell" where known."""

    def __init__(self, place, rule):
        super().__init__(place + ": " + rule)
        self.place, self.rule = place, rule


def _plain(value):
    text = format(value.normalize(), "f")
    return text if text not in ("-0", "") else "0"


def stored(text):
    """The shortest decimal that round-trips the stored number, without exponent or trailing zeros."""
    if not isinstance(text, str) or not PLAIN.match(text.strip()):
        raise IeaRefused(str(text), "not a plain number")
    number = float(text)
    if not math.isfinite(number):
        raise IeaRefused(text, "not a finite number")
    return _plain(Decimal(repr(number)))


def _percent_of_stored(text):
    return _plain(Decimal(stored(text)) * 100)


def _share(part, total):
    value = Fraction(Decimal(part)) / Fraction(Decimal(total)) * 100
    quotient = Decimal(value.numerator) / Decimal(value.denominator)
    return str(quotient.quantize(Decimal("0.1"), ROUND_HALF_EVEN))


class _Sheet:
    def __init__(self, name, cells):
        self.name, self.cells = name, cells

    def place(self, ref):
        return self.name + "!" + ref

    def refuse(self, ref, rule):
        raise IeaRefused(self.place(ref), rule)

    def expect(self, ref, text):
        if self.cells.get(ref) != text:
            self.refuse(ref, "expected " + repr(text))

    def label(self, column, row):
        text = self.cells.get(column + str(row))
        return None if text is None or isinstance(text, Number) else text

    def number(self, column, row):
        ref = column + str(row)
        text = self.cells.get(ref)
        try:
            return stored(text)
        except IeaRefused:
            self.refuse(ref, "expected a number")

    def last_row(self):
        return max(int(re.sub(r"[A-Z]+", "", ref)) for ref in self.cells)

    def find(self, column, text):
        """The rows whose label in the column is exactly `text`."""
        return [row for row in range(1, self.last_row() + 1) if self.label(column, row) == text]

    def only(self, column, text, ref=None):
        rows = self.find(column, text)
        if len(rows) != 1:
            self.refuse(ref or column + (str(rows[0]) if rows else "1"),
                        repr(text) + " must appear exactly once in column " + column)
        return rows[0]

    def notes_after(self, row):
        return [self.cells[ref] for ref in sorted(self.cells, key=lambda ref: int(ref[1:]) if A_CELL.match(ref) else 0)
                if A_CELL.match(ref) and int(ref[1:]) > row and self.cells[ref].strip()
                and not isinstance(self.cells[ref], Number)]


def _demand_keys():
    keys = {"2025": "B"}
    for scenario, start, _ in SCENARIOS:
        for index, year in enumerate(FORECAST_YEARS):
            keys[scenario + "-" + year] = chr(ord(start) + index)
    return keys


def _check_demand_headers(sheet):
    sheet.expect("A2", DEMAND_TITLE)
    sheet.expect("B5", "2025")
    for _, start, name in SCENARIOS:
        sheet.expect(start + "4", name)
        for index, year in enumerate(FORECAST_YEARS):
            sheet.expect(chr(ord(start) + index) + "5", year)


def _demand(sheet, title, titles):
    start = sheet.only("A", title)
    columns, rows, end = _demand_keys(), [], None
    row = start + 1
    while row <= sheet.last_row():
        label = sheet.label("A", row)
        if label in titles:
            break
        if label is not None and label.strip() == SHARE_LABEL:
            end = row
            break
        if label is not None:
            rows.append({"label": label, "values": {key: sheet.number(column, row) for key, column in columns.items()}})
        row += 1
    if end is None:
        sheet.refuse("A" + str(start), "no row labelled " + repr(SHARE_LABEL) + " ends the block")
    if TOTAL_DEMAND not in [item["label"] for item in rows]:
        sheet.refuse("A" + str(start), "the block has no " + repr(TOTAL_DEMAND) + " row")
    share = {key: _percent_of_stored(sheet.number(column, end)) for key, column in columns.items()}
    return {"rows": rows, "energy_share": share}, end


def _supply(sheet, mining, refining):
    row = sheet.only("A", mining)
    if sheet.only("G", refining) != row:
        sheet.refuse("G" + str(row), repr(refining) + " must be on the row of " + repr(mining))
    blocks, end = [], row
    for label_column, value_columns, title in (("A", "BCDE", mining), ("G", "HIJK", refining)):
        top = row + 1
        while sheet.label(label_column, top) != TOP3:
            if sheet.label(label_column, top) is None or top > sheet.last_row():
                sheet.refuse(label_column + str(row), "no row labelled " + repr(TOP3) + " ends the block")
            top += 1
        columns = dict(zip(SUPPLY_YEARS, value_columns))
        lines = [(sheet.label(label_column, line), {year: sheet.number(column, line) for year, column in columns.items()})
                 for line in range(row + 1, top - 1)]
        if len(lines) < 1:
            sheet.refuse(label_column + str(row), "the block has no countries")
        total_label = sheet.label(label_column, top - 1)
        total = {year: sheet.number(column, top - 1) for year, column in columns.items()}
        for year, text in total.items():
            if Fraction(Decimal(text)) <= 0:
                sheet.refuse(columns[year] + str(top - 1), "the total must be positive")

        def shares(values):
            return {year: _share(values[year], total[year]) for year in SUPPLY_YEARS}
        countries = [{"country": label, "values": values, "shares": shares(values)}
                     for label, values in lines if label != REST]
        rest = next(({"values": values, "shares": shares(values)} for label, values in lines if label == REST), None)
        top3 = {year: _percent_of_stored(sheet.number(column, top)) for year, column in columns.items()}
        blocks.append({"stage": title, "countries": countries, "rest": rest, "total_label": total_label,
                       "total": total, "top3_published": top3})
        end = max(end, top)
    return blocks, end


def read(demand, supply):
    """One mineral dict per MINERALS entry, in order, from the cells of the demand and supply sheets."""
    demand_sheet, supply_sheet = _Sheet(DEMAND_SHEET, demand), _Sheet(SUPPLY_SHEET, supply)
    _check_demand_headers(demand_sheet)
    supply_sheet.expect("A2", SUPPLY_TITLE)
    for index, year in enumerate(SUPPLY_YEARS):
        supply_sheet.expect("BCDE"[index] + "4", year)
        supply_sheet.expect("HIJK"[index] + "4", year)
    titles = {entry[0] for entry in MINERALS.values()}
    built, demand_end, supply_end = [], 0, 0
    for key, (title, mining, refining, chapter) in MINERALS.items():
        demand_part, end = _demand(demand_sheet, title, titles)
        supply_part, stop = _supply(supply_sheet, mining, refining)
        demand_end, supply_end = max(demand_end, end), max(supply_end, stop)
        built.append({"id": key, "name": title, "chapter": chapter, "scope_note": SCOPE_NOTES.get(key),
                      "demand": demand_part, "supply": supply_part})
    notes = {"demand": demand_sheet.notes_after(demand_end), "supply": supply_sheet.notes_after(supply_end)}
    for item in built:
        item["notes"] = {name: list(lines) for name, lines in notes.items()}
    return built

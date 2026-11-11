"""Reader for two more sheets of the retained IEA Critical Minerals Dataset 2026 workbook (metals-iea-uses-0.1).

Sheet 3.2 gives demand for energy technologies by mineral (kt); sheet 3.1 splits it by technology. Like metals_iea it
reads no file: the cells arrive as {cell: text}, the layout is checked cell by cell and any mismatch refuses the whole
part. Every figure is the workbook's own number as its shortest round-trip decimal, or a share of the workbook's
printed block total; nothing is curated except the fixed mapping of the IEA's names to USGS chapters. A 3.1 block that
attaches to a 3.2 row must print the same total as that row on every key: the shares divide by the block total, the
reply carries the 3.2 row, and the page's reader recomputes each share from what the reply carries.
"""
from decimal import Decimal
from fractions import Fraction

from second_order.metals_iea import FORECAST_YEARS, SCENARIOS, IeaRefused, _Sheet, _demand_keys, _share
from second_order.thesis_workbook import Number

ENGINE = "metals-iea-uses-0.1"
BY_MINERAL = "3.2 Energy demand by mineral"
BY_TECH = "3.1 Energy demand by tech"
MINERAL_TITLE = "Mineral demand for energy technologies - by mineral (kt)"
TECH_TITLE = "Mineral demand for energy technologies - by mineral and sector (kt)"
RARE = "Rare earth elements as the IEA lists them, not all rare earths"
PGM = "The IEA counts iridium apart from the other PGMs"
HAFNIUM_ZIRCONIUM = "The IEA counts each element apart"
BLOCK_TOTAL_DIFFERS = "the block total differs from the mineral's row in sheet 3.2"
UNMAPPED = "is not a mineral this version maps"
# Sheet 3.2's labels that are not chapters, skipped by name; any other label not in MAPPING refuses the part, so a
# renamed or added IEA mineral never drops out unseen.
SKIPPED = ("Boron", "Total")
# IEA name -> (USGS chapter, scope note).
MAPPING = {name: (chapter, note) for name, chapter, note in [
    ("Cadmium", "cadmium", None), ("Chromium", "chromium", None), ("Copper", "copper", None),
    ("Cobalt", "cobalt", None), ("Gallium", "gallium", None), ("Germanium", "germanium", None),
    ("Battery-grade graphite", "graphite-natural", "Battery grade, natural and synthetic; USGS counts natural graphite"),
    ("Hafnium", "zirconium-and-hafnium", HAFNIUM_ZIRCONIUM), ("Zirconium", "zirconium-and-hafnium", HAFNIUM_ZIRCONIUM),
    ("Indium", "indium", None),
    ("Iridium", "platinum-group-metals", PGM), ("PGMs (other than iridum)", "platinum-group-metals", PGM),
    ("Lead", "lead", None), ("Lithium", "lithium", "lithium content"),
    ("Magnesium", "magnesium-metal", "The IEA counts magnesium; USGS's chapter is magnesium metal"),
    ("Manganese", "manganese", None), ("Molybdenum", "molybdenum", None), ("Nickel", "nickel", None),
    ("Niobium", "niobium-columbium", None), ("Selenium", "selenium", None), ("Silicon", "silicon", None),
    ("Silver", "silver", None), ("Tantalum", "tantalum", None), ("Tellurium", "tellurium", None), ("Tin", "tin", None),
    ("Titanium", "titanium-and-titanium-dioxide", "The IEA counts titanium; USGS has two titanium chapters"),
    ("Tungsten", "tungsten", None), ("Vanadium", "vanadium", None), ("Zinc", "zinc", None),
    ("Arsenic", "arsenic", None),
    ("Neodymium", "rare-earths", RARE), ("Dysprosium", "rare-earths", RARE), ("Praseodymium", "rare-earths", RARE),
    ("Terbium", "rare-earths", RARE), ("Lanthanum", "rare-earths", RARE),
    ("Total rare earth elements", "rare-earths", RARE), ("Yttrium", "yttrium", None)]}


class IeaUsesRefused(IeaRefused):
    """The cells are not the IEA layout this reader understands. `place` is "sheet!cell" where known."""


class _UsesSheet(_Sheet):
    def refuse(self, ref, rule):
        raise IeaUsesRefused(self.place(ref), rule)


def _check_headers(sheet, title_ref, title, scenario_row, year_row):
    sheet.expect(title_ref, title)
    sheet.expect("B" + str(year_row), "2025")
    for _, start, name in SCENARIOS:
        sheet.expect(start + str(scenario_row), name)
        for index, year in enumerate(FORECAST_YEARS):
            sheet.expect(chr(ord(start) + index) + str(year_row), year)


def _has_values(sheet, row):
    return isinstance(sheet.cells.get("B" + str(row)), Number)


def _values(sheet, row, columns):
    return {key: sheet.number(column, row) for key, column in columns.items()}


def _blocks(sheet, columns):
    """{lowercase mineral name: {"total": values, "row": its row, "rows": [(label, values)]}} from sheet 3.1, blocks of
    a name row, technology rows and a "Total <name>" row."""
    blocks, name, rows = {}, None, []
    for row in range(7, sheet.last_row() + 1):
        label = sheet.label("A", row)
        if label is None or not label.strip():
            continue
        if not _has_values(sheet, row):
            if rows:
                sheet.refuse("A" + str(row), "the block of " + repr(name) + " has no Total row")
            name = label.strip()
            continue
        if name is None:
            sheet.refuse("A" + str(row), "a row with values before any mineral name")
        if label.strip().lower().startswith("total "):
            if label.strip()[6:].strip().lower() != name.lower():
                sheet.refuse("A" + str(row), "the total must be that of " + repr(name))
            if name.lower() in blocks:
                sheet.refuse("A" + str(row), repr(name) + " has two blocks")
            blocks[name.lower()] = {"total": _values(sheet, row, columns), "row": row, "rows": rows}
            name, rows = None, []
        else:
            rows.append((label, _values(sheet, row, columns)))
    if rows:
        sheet.refuse("A" + str(sheet.last_row()), "the block of " + repr(name) + " has no Total row")
    return blocks


def _technologies(block):
    if block is None:
        return None
    total = block["total"]["2025"]
    positive = Fraction(Decimal(total)) > 0
    return [{"label": label, "values": values,
             "share_2025": _share(values["2025"], total) if positive else None} for label, values in block["rows"]]


def _attached(sheet, block, total, columns):
    """The block, once its Total row is checked to print the 3.2 row's stored value on every key (refused at the first
    cell of that row that differs), or None when no block attaches."""
    if block is not None:
        for key, column in columns.items():
            if block["total"][key] != total[key]:
                sheet.refuse(column + str(block["row"]), BLOCK_TOTAL_DIFFERS)
    return block


def read(by_mineral, by_tech):
    """One entry per IEA row of sheet 3.2 that maps to a USGS chapter, in sheet order; the rows SKIPPED names are left
    out, and any other label MAPPING does not hold refuses the part at its A cell. A block of sheet 3.1 attaches
    only when its name equals the 3.2 name, ignoring case, and then its Total row must equal the 3.2 row on every key;
    otherwise `technologies` is null."""
    minerals, techs = _UsesSheet(BY_MINERAL, by_mineral), _UsesSheet(BY_TECH, by_tech)
    _check_headers(minerals, "A3", MINERAL_TITLE, 5, 6)
    _check_headers(techs, "A2", TECH_TITLE, 4, 5)
    columns = _demand_keys()
    blocks = _blocks(techs, columns)
    entries, seen = [], set()
    for row in range(8, minerals.last_row() + 1):
        label = minerals.label("A", row)
        name = label.strip() if label is not None else None
        if not name or name in SKIPPED:
            continue
        if name not in MAPPING:
            minerals.refuse("A" + str(row), UNMAPPED)
        if name in seen:
            minerals.refuse("A" + str(row), repr(name) + " must appear once")
        seen.add(name)
        chapter, note = MAPPING[name]
        total = _values(minerals, row, columns)
        entries.append({"name": name, "chapter": chapter, "scope_note": note, "total": total,
                        "technologies": _technologies(_attached(techs, blocks.get(name.lower()), total, columns))})
    return entries

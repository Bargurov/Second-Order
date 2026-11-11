"""SYNTHETIC sources for the metals tools' tests.

The USGS part: rows in the shape of the retained Mineral Commodity Summaries 2026 data-release CSV (12 columns; world
total rows named "World total" with a detail ending ": rounded"; "Other countries" rows; import-source and net-import-
reliance rows). The file is made up. The figures the design's worked examples name copy the published values (cobalt
mine production 2025, copper reserves and mine production 2025) so those examples reproduce from synthetic rows.
"""
import csv
import io
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from second_order import metals_usgs  # noqa: E402

WORLD_SECTION = "World Mine Production and Reserves"
SALIENT = "Salient Statistics—United States"
NOTE = "Synthetic note."
# The copper price series of the thesis price record, as the data release prints it (the published values, so the event
# chains' measured block reproduces from synthetic rows): {year: (value, Notes)}.
PRICE_DETAIL = "Price, annual average, cents per pound: U.S. producer, cathode (COMEX + premium)"
PRICES = {2021: ("432.3", ""), 2022: ("410.8", ""), 2023: ("395.3", ""), 2024: ("431.8", ""),
          2025: ("490", "Estimated.")}


def _row(chapter, commodity, country, statistic, detail, unit, year, value, section=WORLD_SECTION, critical="Yes",
         other=""):
    return [chapter, section, commodity, country, statistic, detail, unit, year, value, NOTE, critical, other]


def _table(chapter, commodity, statistic, detail, world_detail, unit, year, figures, world, other=None, critical="Yes"):
    """Country rows, an optional Other countries row and the world total row of one series."""
    rows = [_row(chapter, commodity, country, statistic, detail, unit, year, value, critical=critical)
            for country, value in figures]
    if other is not None:
        rows.append(_row(chapter, commodity, "Other countries", statistic, detail, unit, year, other, critical=critical))
    rows.append(_row(chapter, commodity, "World total", statistic, world_detail, unit, year, world, critical=critical))
    return rows


def usgs_rows(swap_tie=False, prices: dict[int, tuple[str, str]] | None = None):
    """The synthetic file as rows (header first). `swap_tie` swaps the order of the two tied lead rows. `prices` are the
    copper price rows {year: (value, Notes)} (default PRICES)."""
    tm = "metric tons"
    rows = [list(metals_usgs.HEADER)]
    # COBALT: published 2025 mine production; the world row is "rounded" and joins the country rows.
    rows += _table("COBALT", "Cobalt", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("United States", "300"), ("Congo (Kinshasa)", "230,000"), ("Indonesia", "44,000")],
                   "310,000", other="9,100")
    # COPPER: published 2025 reserves and mine production (43 years at the 2025 rate).
    rows += _table("COPPER", "Copper", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Chile", "5,300"), ("Congo (Kinshasa)", "3,300")], "23,000", other="14,400", critical="No")
    rows += _table("COPPER", "Copper", "Reserves", "Reserves", "Reserves: rounded", tm, "2025",
                   [("Chile", "190,000"), ("Peru", "120,000")], "980,000", other="670,000", critical="No")
    # BAUXITE: the qualifier sits in the detail and the rounded marker follows a comma.
    rows += _table("BAUXITE AND ALUMINA", "Bauxite", "Production", "Bauxite, mine production",
                   "Bauxite, mine production, rounded", tm, "2025", [("Guinea", "130"), ("Australia", "100")], "450")
    rows += _table("BAUXITE AND ALUMINA", "Bauxite", "Reserves", "Bauxite reserves", "Bauxite reserves: rounded", tm,
                   "2025", [("Guinea", "7,400"), ("Australia", "3,500")], "29,000")
    # IRON ORE: reserves and production are stated on different bases, so they never pair.
    rows += _table("IRON ORE", "Iron ore", "Production", "Mine production: Iron content",
                   "Mine production: Iron content, rounded", tm, "2025", [("Australia", "930"), ("Brazil", "250")],
                   "1,500")
    rows += _table("IRON ORE", "Iron ore", "Reserves", "Reserves (million metric tons): Crude ore",
                   "Reserves (million metric tons): Crude ore, rounded", tm, "2025",
                   [("Australia", "58,000"), ("Brazil", "34,000")], "190,000")
    # TITANIUM: the world detail is lowercase and sits after a colon; a world-only series has no country rows.
    rows += _table("TITANIUM AND TITANIUM DIOXIDE", "Titanium", "Production", "Mine production: Ilmenite",
                   "Mine production: ilmenite, rounded", tm, "2025", [("Australia", "400"), ("China", "2,000")],
                   "6,000")
    rows.append(_row("TITANIUM AND TITANIUM DIOXIDE", "Titanium", "World total", "Production",
                     "Mine production: ilmenite and rutile, rounded", tm, "2025", "7,000"))
    # Two 2025 reliance rows under one detail, told apart only by the Commodity column (as the real file prints them).
    for commodity, value in (("Titanium sponge metal", "100"), ("TiO2 pigment", "E")):
        rows.append(_row("TITANIUM AND TITANIUM DIOXIDE", commodity, "United States", "Net import reliance",
                         "Net import reliance as a percentage of apparent consumption", "percent", "2025", value,
                         section=SALIENT))
    # RARE EARTHS: a qualified world total, import sources and net import reliance.
    rows += _table("RARE EARTHS", "Rare earths", "Production", "Mine production", "Mine production: rounded", tm,
                   "2025", [("China", "270,000"), ("United States", "45,000")], ">2,000,000")
    for country, value in (("China", "70"), ("Malaysia", "13"), ("Other countries", "17")):
        rows.append(_row("RARE EARTHS", "Rare earths", country, "Import sources 2021-2024",
                         "Rare-earth compounds and metals", "percent", "2021–24", value, section="Import Sources"))
    rows.append(_row("RARE EARTHS", "Rare earths", "China", "Import sources 2021-2024", "Rare-earth magnets",
                     "percent", "2021–24", "93", section="Import Sources"))
    for year, value in (("2024", "E"), ("2025", ">95")):
        rows.append(_row("RARE EARTHS", "Rare earths", "United States", "Net import reliance",
                         "Net import reliance as a percentage of apparent consumption", "percent", year, value,
                         section=SALIENT))
    # NICKEL: the United States is withheld, so the order is unknown.
    rows += _table("NICKEL", "Nickel", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Indonesia", "2,200,000"), ("United States", "W"), ("Philippines", "330,000")], "3,700,000")
    # LEAD: two countries tie for third place; the one named first alphabetically takes the place.
    tie = [("Zeta", "5"), ("Alpha", "5")]
    rows += _table("LEAD", "Lead", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Big", "50"), ("Mid", "20")] + (tie[::-1] if swap_tie else tie), "100")
    # GOLD: only two named countries, so there is no top three; the world total is printed twice for GALLIUM.
    rows += _table("GOLD", "Gold", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Australia", "300"), ("China", "380")], "3,000")
    rows += _table("GALLIUM", "Gallium", "Production", "Primary production", "Primary production: rounded", tm,
                   "2025", [("China", "700")], "800")
    rows.append(_row("GALLIUM", "Gallium", "World total", "Production", "Primary production: rounded", tm, "2025",
                     "900"))
    # TIN: a country printed as a dash counts as zero in the order (it never outranks a positive value, though its
    # name comes first) and gets no share; the world total is not marked rounded.
    rows += _table("TIN", "Tin", "Production", "Mine production", "Mine production", tm, "2025",
                   [("Delta", "—"), ("Kappa", "40"), ("Omega", "30"), ("Sigma", "20")], "100")
    # VANADIUM: the reserves series has the id of the one metals_usgs.UNIT_ISSUES names (the real file labels it metric
    # tons where the printed chapter says thousand metric tons), so its quantities and years are withheld.
    rows += _table("VANADIUM", "Vanadium", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Epsilon", "70,000"), ("Theta", "20,000")], "100,000")
    rows += _table("VANADIUM", "Vanadium", "Reserves", "Reserves", "Reserves: rounded", tm, "2025",
                   [("Epsilon", "5,000"), ("Theta", "10,000")], "20,000")
    # SILVER: reserves smaller than one year of output, both in the same unit and with no known issue: a valid ratio
    # under one year, shown as "less than 1".
    rows += _table("SILVER", "Silver", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Iota", "600"), ("Lambda", "300")], "1,000")
    rows += _table("SILVER", "Silver", "Reserves", "Reserves", "Reserves: rounded", tm, "2025",
                   [("Iota", "300"), ("Lambda", "100")], "500")
    # COPPER, continued: a refinery table led by another country than the mine table, and US secondary production.
    rows += _table("COPPER", "Copper", "Production", "Refinery production", "Refinery production: rounded", tm, "2025",
                   [("China", "12,000"), ("Chile", "2,000")], "27,000", critical="No")
    for detail, unit, year, value in (("Mine production", "thousand metric tons", "2025", "1,100"),
                                      ("Secondary production (new and old scrap)", "thousand metric tons", "2025", "820"),
                                      ("Secondary production (new and old scrap)", "thousand metric tons", "2024", "800"),
                                      ("Recovered from scrap, old", "thousand metric tons", "2025", "W")):
        rows.append(_row("COPPER", "Copper", "United States", "Production", detail, unit, year, value, section=SALIENT,
                         critical="No"))
    # COPPER, continued: the U.S. producer cathode price, one row a year; Notes marks an estimate.
    for year, (value, notes) in sorted((PRICES if prices is None else prices).items()):
        row = _row("COPPER", "Copper", "United States", "Price", PRICE_DETAIL, "cents per pound", str(year), value,
                   section=SALIENT, critical="No")
        row[9] = notes
        rows.append(row)
    # COBALT, continued: one complete import group (three named sources) and one with a named source printed as W.
    for country, value in (("Norway", "40"), ("Finland", "30"), ("Japan", "10"), ("Other countries", "20")):
        rows.append(_row("COBALT", "Cobalt", country, "Import sources 2021-2024", "Cobalt metal", "percent", "2021–24",
                         value, section="Import Sources"))
    for country, value in (("Korea", "W"), ("Japan", "50"), ("Other countries", "10")):
        rows.append(_row("COBALT", "Cobalt", country, "Import sources 2021-2024", "Cobalt oxide", "percent", "2021–24",
                         value, section="Import Sources"))
    # MANGANESE: the named production figures sum past the world total; reserves hold a country that production does
    # not name (Gamma) and one whose reserves share is above its production share (Beta).
    rows += _table("MANGANESE", "Manganese", "Production", "Mine production", "Mine production: rounded", tm, "2025",
                   [("Alpha", "60"), ("Beta", "50")], "100")
    rows += _table("MANGANESE", "Manganese", "Reserves", "Reserves", "Reserves: rounded", tm, "2025",
                   [("Alpha", "20"), ("Beta", "60"), ("Gamma", "5")], "100")
    return rows


def usgs_bytes(rows=None):
    """The synthetic rows as the data release stores them: comma-separated text in Windows-1252."""
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator="\r\n").writerows(usgs_rows() if rows is None else rows)
    return out.getvalue().encode("cp1252")


# ---------------------------------------------------------------- the synthetic IEA Critical Minerals Dataset sheets

IEA_DEMAND_SHEET = "1 Total demand for key minerals"
IEA_SUPPLY_SHEET = "2 Total supply for key minerals"
_DEMAND_COLUMNS = ["B"] + list("DEFGH") + list("JKLMN") + list("PQRST")
_SCENARIO_HEADS = {"D4": "Current Policies scenario", "J4": "Stated Policies scenario", "P4": "High Demand Scenario"}
_SHARE_LABEL = "Share of energy technologies in total demand "  # The workbook prints a trailing space.
_COBALT_DEMAND = [("Low emissions power generation", "1.23E-2"), ("Electric vehicles", "84.5"),
                  ("Grid battery storage", "5.92"), ("Hydrogen technologies", "9.7199999999999995E-3"),
                  ("Total energy technologies", "90.4"), ("Other uses", "169"), ("Total demand", "259")]
_OTHER_DEMAND = [("Electric vehicles", "10"), ("Total energy technologies", "10"), ("Other uses", "30"),
                 ("Total demand", "40")]
_COBALT_MINING = [("Democratic Republic of Congo", "210"), ("Indonesia", "48.3"), ("Russia", "7.69"),
                  ("China", "7.38"), ("Australia", "4.15"), ("Zambia", "4.33")]
_COBALT_REFINING = [("China", "180"), ("Finland", "20.3"), ("Japan", "5.83"), ("Indonesia", "6.17"),
                    ("Canada", "6.4"), ("Norway", "2.8")]
_OTHER_SUPPLY = [("Alpha", "50"), ("Beta", "30"), ("Gamma", "10")]
IEA_NOTES_DEMAND = "Notes: Lithium demand is in lithium (Li) content, not carbonate equivalent (LCE). Synthetic."
IEA_NOTES_SUPPLY = ["Notes: Supply projections are synthetic.", "Base case is made up for tests."]


def _grow(text, step):
    """The 2025 figure grown by 10% a step, as the text of a stored number."""
    return text if step == 0 else repr(round(float(text) * (1 + 0.1 * step), 4))


def iea_sheets() -> dict[str, dict[str, str]]:
    """Two sheets of the IEA workbook in the shape thesis_sources.content returns: {cell: text}, numbers as Number.
    The cobalt 2025 figures copy the published ones; every other figure is made up."""
    from second_order import metals_iea
    from second_order.thesis_workbook import Number
    demand = {"A2": "Demand for key energy transition minerals (kt)", **_SCENARIO_HEADS, "B5": "2025"}
    for index, column in enumerate(_DEMAND_COLUMNS[1:]):
        demand[column + "5"] = str(2030 + index % 5 * 5)
    row = 7
    for key, (title, *_rest) in metals_iea.MINERALS.items():
        demand["A" + str(row)] = title
        for label, first in (_COBALT_DEMAND if key == "cobalt" else _OTHER_DEMAND):
            row += 1
            demand["A" + str(row)] = label
            for step, column in enumerate(_DEMAND_COLUMNS):
                demand[column + str(row)] = Number(_grow(first, step))
        row += 1
        demand["A" + str(row)] = _SHARE_LABEL
        for step, column in enumerate(_DEMAND_COLUMNS):
            demand[column + str(row)] = Number("0.34899999999999998" if key == "cobalt" and step == 0 else "0.35")
        row += 3
    demand["A" + str(row - 1)] = IEA_NOTES_DEMAND
    supply = {"A2": "Total supply for key energy transition minerals, base case (kt)"}
    for index, year in enumerate(("2025", "2030", "2035", "2040")):
        supply["BCDE"[index] + "4"] = supply["HIJK"[index] + "4"] = year
    row = 6
    for key, (_t, mining, refining, _c) in metals_iea.MINERALS.items():
        cobalt = key == "cobalt"
        sides = (("A", "BCDE", mining, _COBALT_MINING if cobalt else _OTHER_SUPPLY, "38.6" if cobalt else "10",
                  "Total", "320" if cobalt else "100", "0.83" if cobalt else "0.9"),
                 ("G", "HIJK", refining, _COBALT_REFINING if cobalt else _OTHER_SUPPLY, "16.5" if cobalt else "10",
                  "Total clean technologies" if cobalt else "Total", "238" if cobalt else "100",
                  "0.86799999999999999" if cobalt else "0.9"))
        for label_column, value_columns, title, countries, rest, total_label, total, top3 in sides:
            supply[label_column + str(row)] = title
            lines = list(countries) + [("Rest of world", rest), (total_label, total), ("Top 3 share", top3)]
            for offset, (label, first) in enumerate(lines, 1):
                supply[label_column + str(row + offset)] = label
                for step, column in enumerate(value_columns):
                    shown = first if label == "Top 3 share" else _grow(first, step)
                    supply[column + str(row + offset)] = Number(shown)
        row += len(countries) + 5
    supply["A" + str(row)], supply["A" + str(row + 1)] = IEA_NOTES_SUPPLY
    return {IEA_DEMAND_SHEET: demand, IEA_SUPPLY_SHEET: supply}


USES_MINERAL_TITLE = "Mineral demand for energy technologies - by mineral (kt)"
USES_TECH_TITLE = "Mineral demand for energy technologies - by mineral and sector (kt)"
# sheet 3.2 rows (name, 2025 figure); Boron and Total are skipped by the reader (any other unmapped name refuses)
_USES_MINERALS = [("Boron", "1"), ("Cadmium", "2"), ("Copper", "1000"), ("Iridium", "0.5"),
                  ("PGMs (other than iridum)", "30"), ("Lithium", "200"), ("Neodymium", "0"),
                  ("Total rare earth elements", "10"), ("Total", "9999")]
# sheet 3.1 blocks: (name, total label, [(technology, 2025 figure)], 2025 total)
_USES_BLOCKS = [("Copper", "Total Copper", [("Wind", "100"), ("Other low emissions power generation", "250")], "1000"),
                ("Lithium", "Total lithium", [("Electric vehicles", "150"), ("Grid battery storage", "50")], "200"),
                ("PGMs", "Total PGMs", [("Hydrogen", "10")], "30"),
                ("Neodymium", "Total neodymium", [("Wind", "0")], "0")]


def iea_uses_sheets():
    """Sheets 3.2 and 3.1 of the IEA workbook as {name: {cell: text}}: the real labels and layout, made-up figures."""
    from second_order import metals_iea, metals_iea_uses
    from second_order.thesis_workbook import Number
    by_mineral = {"A3": USES_MINERAL_TITLE, "B6": "2025"}
    by_tech = {"A2": USES_TECH_TITLE, "B5": "2025"}
    for sheet, scenario_row, year_row in ((by_mineral, 5, 6), (by_tech, 4, 5)):
        for _, start, name in metals_iea.SCENARIOS:
            sheet[start + str(scenario_row)] = name
            for index, year in enumerate(metals_iea.FORECAST_YEARS):
                sheet[chr(ord(start) + index) + str(year_row)] = year

    def put(sheet, row, label, first):
        sheet["A" + str(row)] = label
        for step, column in enumerate(_DEMAND_COLUMNS):
            sheet[column + str(row)] = Number(_grow(first, step))
    for offset, (name, first) in enumerate(_USES_MINERALS):
        put(by_mineral, 8 + offset, name, first)
    row = 7
    for name, total_label, techs, total in _USES_BLOCKS:
        by_tech["A" + str(row)] = name
        for label, first in techs:
            row += 1
            put(by_tech, row, label, first)
        row += 1
        put(by_tech, row, total_label, total)
        row += 3
    return {metals_iea_uses.BY_MINERAL: by_mineral, metals_iea_uses.BY_TECH: by_tech}


# ---------------------------------------------------------------- the synthetic retained folder and its sources file

import hashlib  # noqa: E402
import json  # noqa: E402

import thesis_fakes  # noqa: E402

RETAINED = "data/sector-sources/copper"
APPROVAL = "synthetic-metals-owner-01"
FILES = {"usgs-csv-2026": ("MCS2026_Commodities_Data.csv", "csv", 1), "iea-dataset-2026": ("dataset.xlsx", "xlsx", 2)}
_TERMS = {"licence": "Synthetic test terms", "note": "Synthetic: made-up files for tests."}


def _bytes(folder):
    return usgs_bytes() if folder == "usgs-csv-2026" else thesis_fakes.workbook({**iea_sheets(), **iea_uses_sheets()})


def _stamp(folder):
    return f"2026-11-05T08:0{FILES[folder][2]}:00+00:00"


def _record_path(root, folder):
    return Path(root) / "acquisitions" / APPROVAL / f"outcome-{FILES[folder][2]}.json"


def retain(root, folder, data):
    name, kind, attempt = FILES[folder]
    (Path(root) / folder).mkdir(parents=True, exist_ok=True)
    (Path(root) / folder / name).write_bytes(data)
    record = {"approval_id": APPROVAL, "n": attempt, "url": f"https://example.org/synthetic-metals/{folder}/{name}",
              "kind": kind, "outcome": "complete", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "retained": f"{RETAINED}/{folder}/{name}", "origin": "owner_download", "http_status": None,
              "hash_kind": "owner_file", "recorded_at": _stamp(folder)}
    path = _record_path(root, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")


def write_sources(root) -> Path:
    """Retain both synthetic files with owner_download records under root."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for folder in FILES:
        retain(root, folder, _bytes(folder))
    return root


def sources_file(root) -> dict:
    """A sources file (the shape of content/metals/sources.json) whose entries match the retained synthetic files."""
    entries = []
    for folder, (name, kind, attempt) in FILES.items():
        record = json.loads(_record_path(root, folder).read_text(encoding="utf-8"))
        entries.append({"id": folder, "kind": kind, "origin": "owner_download", "publisher": "Synthetic",
                        "title": f"Synthetic {folder}", "series": f"synthetic-{folder}", "edition": "2026",
                        "edition_date": "2026-07-01", "url": record["url"], "approval_id": APPROVAL,
                        "attempt": attempt, "folder": folder, "name": name, "sha256": record["sha256"],
                        "bytes": record["bytes"], "retrieved_at": _stamp(folder), "terms": dict(_TERMS),
                        "transcription": None, "encoding": "windows-1252" if kind == "csv" else None})
    return {"sources_version": "metals-sources-0.1", "sources": entries}


def change_byte(root, folder) -> None:
    """Flip one byte of the retained file (its record stays), so the file no longer matches its record."""
    path = Path(root) / folder / FILES[folder][0]
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))

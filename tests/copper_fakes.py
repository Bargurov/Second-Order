"""SYNTHETIC sources for the copper tools' tests: retained files, the acquisition records that describe them exactly, and
an inputs catalogue bound to them, in the shape copper_inputs reads.

Every file is made up and every label in it says "Synthetic"; no file copies any publication's layout or wording. The
numbers are deliberately the values the real retained sources print (IEA Critical Minerals Dataset 2026; the fiscal
2025 and 2024 annual reports of two producers), so the design's worked example reproduces exactly from synthetic files.
Addresses are under example.org. The catalogue is stated here independently of the committed one: the same figure ids
(the tools' contract), synthetic sources and locators.
"""
import hashlib
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import thesis_fakes  # noqa: E402

RETAINED = "data/sector-sources/copper"
GET_APPROVAL = "synthetic-copper-tools-01"
OWNER_APPROVAL = "synthetic-copper-tools-owner-01"
TERMS = {"licence": "Synthetic test terms", "note": "Synthetic: made-up files for tests; the numbers copy published "
                                                    "values so a worked example reproduces."}
S1, S2, S45 = "1 Total demand for key minerals", "2 Total supply for key minerals", "4.5 Electricity networks"
SCENARIOS = {"cps": "Current Policies scenario", "steps": "Stated Policies scenario", "hd": "High Demand Scenario"}
LINES = {"solar": (8, "Solar PV"), "wind": (9, "Wind"), "other-low-emission": (10, "Other low emissions power generation"),
         "ev": (11, "Electric vehicles"), "grid-storage": (12, "Grid battery storage"),
         "networks": (13, "Electricity networks"), "hydrogen": (14, "Hydrogen technologies"),
         "energy": (15, "Total energy technologies"), "other-uses": (16, "Other uses"), "total": (17, "Total demand")}
COLUMNS = {(None, "2025"): "B", ("cps", "2030"): "D", ("cps", "2035"): "E", ("cps", "2040"): "F",
           ("steps", "2030"): "J", ("steps", "2035"): "K", ("steps", "2040"): "L",
           ("hd", "2030"): "P", ("hd", "2035"): "Q", ("hd", "2040"): "R"}
HEADS = {"cps": "D", "steps": "J", "hd": "P"}
# (scenario, year) -> the ten demand rows in LINES order: solar, wind, other low-emission, EVs, grid storage, networks,
# hydrogen, energy total, other uses, total (copies of the published values).
DEMAND = {
    (None, "2025"): ("1970", "542", "57.8", "794", "137", "4544", "0.00585", "8003", "19772", "27775"),
    ("cps", "2030"): ("2044", "673", "123", "1623", "180", "5637", "0.0119", "10232", "20560", "30792"),
    ("cps", "2035"): ("1731", "636", "100", "2146", "292", "6398", "0.0132", "11296", "21063", "32359"),
    ("cps", "2040"): ("1755", "523", "99.7", "2359", "369", "6693", "0.0104", "11822", "21757", "33580"),
    ("steps", "2030"): ("2222", "791", "128", "1763", "218", "5713", "0.0119", "10765", "20605", "31370"),
    ("steps", "2035"): ("2164", "734", "108", "2561", "350", "6449", "0.0132", "12364", "21158", "33522"),
    ("steps", "2040"): ("2219", "571", "110", "3046", "460", "6631", "0.0104", "13073", "21911", "34984"),
    ("hd", "2030"): ("2803", "1172", "166", "2017", "281", "6002", "0.083", "12302", "19665", "31967"),
    ("hd", "2035"): ("2726", "1038", "155", "3258", "441", "6924", "0.082", "14552", "19742", "34294"),
    ("hd", "2040"): ("2626", "919", "135", "4143", "610", "7181", "0.0824", "15668", "20051", "35719"),
}
COUNTRIES = {"chile": (7, "Chile"), "drc": (8, "Democratic Republic of Congo"), "peru": (9, "Peru"),
             "china": (10, "China"), "russia": (11, "Russia"), "us": (12, "United States"),
             "rest": (13, "Rest of world"), "total": (14, "Total")}
MINE = {"chile": ("5485", "5369", "4841", "4165"), "drc": ("3338", "4212", "3041", "2696"),
        "peru": ("2726", "2712", "2384", "1859"), "china": ("1838", "2040", "1965", "1852"),
        "russia": ("1145", "1244", "1424", "1343"), "us": ("1101", "1196", "823", "632"),
        "rest": ("7594", "7798", "6255", "4636"), "total": ("23227", "24571", "20733", "17183")}
SUPPLY_YEARS = ("2025", "2030", "2035", "2040")
MINE_COLUMNS, REFINING_COLUMNS = ("B", "C", "D", "E"), ("H", "I", "J", "K")
REFINING = ("27955", "36383", "34501", "33710")
DC = {(None, "2025"): "4192", ("steps", "2030"): "5724", ("steps", "2035"): "6403", ("steps", "2040"): "6097",
      ("hd", "2030"): "5993", ("hd", "2035"): "6850", ("hd", "2040"): "6645"}
TITLE1 = "Synthetic: demand for key energy transition minerals (kt)"
TITLE2 = "Synthetic: total supply for key energy transition minerals, base case (kt)"
TITLE45 = "Synthetic: mineral demand for electricity networks (kt)"
NOTE_PIPELINE = "Synthetic note: a stand-in for the supply sheet's note on how its projections are built."
NOTE_BASE = "Synthetic note: a stand-in for the supply sheet's note on how its base case is weighted."
DC_LABEL = "Wider direct current (DC) technology development"


def _grouped(value: str) -> str:
    whole, _, fraction = value.partition(".")
    return f"{int(whole):,}" + (f".{fraction}" if fraction else "")


# ---------------------------------------------------------------- the synthetic workbook

def iea_sheets() -> dict[str, dict[str, str]]:
    one = {"A2": TITLE1, "A7": "Copper", **{f"{HEADS[key]}4": label for key, label in SCENARIOS.items()}}
    for (scenario, year), column in COLUMNS.items():
        one[f"{column}5"] = year
        for (_, (row, label)), value in zip(LINES.items(), DEMAND[(scenario, year)]):
            one[f"A{row}"], one[f"{column}{row}"] = label, value
    two = {"A2": TITLE2, "A6": "Copper - Mining", "G6": "Copper - Refining", "A72": NOTE_PIPELINE, "A73": NOTE_BASE}
    for index, year in enumerate(SUPPLY_YEARS):
        two[f"{MINE_COLUMNS[index]}4"] = two[f"{REFINING_COLUMNS[index]}4"] = year
        for country, (row, label) in COUNTRIES.items():
            two[f"A{row}"], two[f"{MINE_COLUMNS[index]}{row}"] = label, MINE[country][index]
        two["G14"], two[f"{REFINING_COLUMNS[index]}14"] = "Total", REFINING[index]
    networks = {"A2": TITLE45, "A7": "Base case", "A8": "Copper", "A11": DC_LABEL, "A12": "Copper",
                **{f"{HEADS[key]}4": label for key, label in SCENARIOS.items()}}
    for (scenario, year), column in COLUMNS.items():
        networks[f"{column}5"] = year
        networks[f"{column}8"] = DEMAND[(scenario, year)][5]
        if (scenario, year) in DC:
            networks[f"{column}12"] = DC[(scenario, year)]
    return {S1: one, S2: two, S45: networks}


# ---------------------------------------------------------------- the synthetic annual reports

class Page:
    """A made-up HTML page whose every block is one paragraph of the project's reader, numbered as it is built."""

    def __init__(self, title: str):
        self.parts, self.count = [], 0
        self.title = title
        self.p(f"{title}. Synthetic: made up for tests.")

    def p(self, text: str) -> int:
        self.parts.append(f"<p>{escape(text, quote=False)}</p>")
        self.count += 1
        return self.count

    def row(self, *cells: str) -> list[int]:
        self.parts.append("<tr>" + "".join(f"<td>{escape(cell, quote=False)}</td>" for cell in cells) + "</tr>")
        numbers = list(range(self.count + 1, self.count + len(cells) + 1))
        self.count += len(cells)
        return numbers

    def html(self) -> bytes:
        body, open_table = [], False
        for part in self.parts:
            if part.startswith("<tr>") and not open_table:
                body.append("<table>")
                open_table = True
            elif not part.startswith("<tr>") and open_table:
                body.append("</table>")
                open_table = False
            body.append(part)
        if open_table:
            body.append("</table>")
        return ("<!DOCTYPE html>\n<html><head><title>" + escape(self.title) + "</title></head><body>\n"
                + "\n".join(body) + "\n</body></html>\n").encode("utf-8")


def _cell(figure_id, source, measure, unit, shown, value, year, header, label, column, cell, label_text, header_text):
    return {"id": figure_id, "source": source, "measure": measure, "unit": unit, "value": value, "as_shown": shown,
            "year": year, "basis": None, "scenario": None,
            "locator": {"paragraph": cell, "label_paragraph": label, "label": label_text, "column": column,
                        "header_paragraph": header, "header": header_text}, "checks": []}


def _prose(figure_id, source, measure, unit, shown, value, year, paragraph, quote):
    return {"id": figure_id, "source": source, "measure": measure, "unit": unit, "value": value, "as_shown": shown,
            "year": year, "basis": None, "scenario": None, "locator": {"paragraph": paragraph, "quote": quote},
            "checks": []}


def _table(page: Page, source: str, prefix: str, division: str, rows: list[tuple]) -> list[dict]:
    """A synthetic division table: a header row naming the year, then one row per figure (label, then cells)."""
    header = page.row("Synthetic table", "2025", "2024")[1]
    figures = []
    for key, label, cells, column, shown, value, unit, measure in rows:
        numbers = page.row(label, *cells)
        cell = [n for n, text in zip(numbers[1:], cells) if text not in ("$", "a", "b", "—")][column - 1]
        figures.append(_cell(f"{prefix}-{key}-2025", source, f"Synthetic {division}: {measure}", unit, shown, value,
                             "2025", header, numbers[0], column, cell, label, "2025"))
    return figures


def fcx_2025() -> tuple[Page, list[dict], list[dict]]:
    page, source, figures, passages = Page("Synthetic Producer A annual report, fiscal 2025"), "fcx-synthetic-2025", [], []
    lb = "usd_per_lb"
    figures += _table(page, source, "fcx-us", "U.S. mines", [
        ("revenue", "Revenues", ["$", "4.91", "$", "4.91"], 1, "4.91", "4.91", lb, "revenue per pound"),
        ("site-costs", "Site production and delivery", ["3.51", "3.10"], 1, "3.51", "3.51", lb, "site costs per pound"),
        ("credits", "By-product credits", ["(0.59)", "—"], 1, "(0.59)", "-0.59", lb, "by-product credits"),
        ("treatment", "Treatment charges", ["0.13", "0.12"], 1, "0.13", "0.13", lb, "treatment charges"),
        ("unit-net", "Unit net cash costs", ["3.05", "3.22"], 1, "3.05", "3.05", lb, "unit net cash cost"),
        ("co-product", "Unit net cash costs, co-product", ["3.05", "3.22"], 2, "3.22", "3.22", lb, "co-product cost"),
        ("gross-profit", "Gross profit per pound", ["$", "1.30", "$", "1.19"], 1, "1.30", "1.30", lb, "gross profit"),
        ("sales", "Copper sales (millions of recoverable pounds)", ["1,301", "1,263"], 1, "1,301", "1301", "mlb",
         "copper sales")])
    figures += _table(page, source, "fcx-sa", "South America", [
        ("revenue", "Revenues, excluding adjustments", ["$", "4.79", "$", "4.79"], 1, "4.79", "4.79", lb, "revenue"),
        ("site-costs", "Site production and delivery", ["2.82", "a", "2.56"], 1, "2.82", "2.82", lb, "site costs"),
        ("credits", "By-product credits", ["(0.47)", "—"], 1, "(0.47)", "-0.47", lb, "credits"),
        ("treatment", "Treatment charges", ["0.07", "0.07"], 1, "0.07", "0.07", lb, "treatment charges"),
        ("royalty", "Royalty on metals", ["0.01", "0.01"], 1, "0.01", "0.01", lb, "royalty"),
        ("unit-net", "Unit net cash costs", ["2.43", "2.64"], 1, "2.43", "2.43", lb, "unit net cash cost"),
        ("co-product", "Unit net cash costs, co-product", ["2.43", "2.64"], 2, "2.64", "2.64", lb, "co-product cost"),
        ("gross-profit", "Gross profit per pound", ["$", "1.89", "$", "1.73"], 1, "1.89", "1.89", lb, "gross profit"),
        ("sales", "Copper sales (millions of recoverable pounds)", ["1,073", "1,177"], 1, "1,073", "1073", "mlb",
         "copper sales")])
    figures += _table(page, source, "fcx-id", "Indonesia", [
        ("revenue", "Revenues, excluding adjustments", ["$", "4.53", "$", "4.53"], 1, "4.53", "4.53", lb, "revenue"),
        ("site-costs", "Site production and delivery", ["1.86", "1.10"], 1, "1.86", "1.86", lb, "site costs"),
        ("credits", "Gold, silver and other by-product credits", ["(3.17)", "—"], 1, "(3.17)", "-3.17", lb,
         "credits"),
        ("treatment", "Treatment charges", ["0.19", "0.11"], 1, "0.19", "0.19", lb, "treatment charges"),
        ("export-duties", "Export duties", ["0.28", "0.16"], 1, "0.28", "0.28", lb, "export duties"),
        ("royalty", "Royalty on metals", ["0.29", "0.17"], 1, "0.29", "0.29", lb, "royalty"),
        ("unit-net", "Unit net cash (credits) costs", ["(0.55)", "1.54"], 1, "(0.55)", "-0.55", lb, "unit net cost"),
        ("co-product", "Unit net cash costs, co-product", ["(0.55)", "1.54"], 2, "1.54", "1.54", lb, "co-product cost"),
        ("gross-profit", "Gross profit per pound", ["$", "3.30", "$", "1.95"], 1, "3.30", "3.30", lb, "gross profit"),
        ("sales", "Copper sales (millions of recoverable pounds)", ["1,205", "1,632"], 1, "1,205", "1205", "mlb",
         "copper sales")])
    consolidated = _table(page, source, "fcx", "consolidated", [
        ("realized-price", "Average realized price per pound", ["$", "4.75", "$", "4.21"], 1, "4.75", "4.75", lb,
         "realized price"),
        ("site-costs", "Site production and delivery costs per pound", ["$", "2.75", "$", "2.49"], 1, "2.75", "2.75",
         lb, "site costs"),
        ("unit-net", "Unit net cash costs per pound", ["$", "1.65", "$", "1.56"], 1, "1.65", "1.65", lb, "unit net"),
        ("sales", "Sales, excluding purchases", ["3,574", "4,066"], 1, "3,574", "3574", "mlb", "copper sales")])
    figures += consolidated
    quote = "Synthetic: excludes $0.17 per pound of made-up idle facility costs."
    figures.append(_prose("fcx-mud-rush-2025", source, "Synthetic excluded costs per pound", lb, "$0.17", "0.17",
                          "2025", page.p(quote), quote))
    passages.append({"id": "fcx-sales-label", "source": source,
                     "locator": {"paragraph": figures[7]["locator"]["label_paragraph"],
                                 "quote": "Copper sales (millions of recoverable pounds)"}})
    for pid, text in (("fcx-by-product-method", "Synthetic: other metal revenues are credits in the by-product method."),
                      ("fcx-co-product-method", "Synthetic: shared costs are allocated by revenue in the co-product "
                                                "method.")):
        passages.append({"id": pid, "source": source, "locator": {"paragraph": page.p(text), "quote": text}})
    since = "Synthetic: the mine has operated without a break since 1945."
    passages.append({"id": "fcx-bagdad-since", "source": source,
                     "locator": {"paragraph": page.p(since), "quote": since}})
    bagdad = ("Synthetic: the reserve life exceeds 80 years. The studies are updated before a decision during 2026. "
              "They would increase copper production by 200 to 250 million pounds per year. Capital would approximate "
              "$3.5 billion. The expansion would require an incentive copper price of approximately $4.00 per pound "
              "and three to four years to complete.")
    number = page.p(bagdad)
    for fid, shown, value, unit, quote, measure in (
            ("fcx-bagdad-low-2025", "200", "200", "mlb_per_year", "increase copper production by 200 to 250 million "
                                                                  "pounds per year", "stated added production, lower end"),
            ("fcx-bagdad-high-2025", "250", "250", "mlb_per_year", "increase copper production by 200 to 250 million "
                                                                   "pounds per year", "stated added production, upper end"),
            ("fcx-bagdad-capital-2025", "$3.5", "3.5", "usd_billion", "Capital would approximate $3.5 billion.",
             "stated capital (approximate)"),
            ("fcx-bagdad-incentive-2025", "$4.00", "4.00", lb, "incentive copper price of approximately $4.00 per "
                                                               "pound", "stated incentive copper price")):
        figures.append(_prose(fid, source, f"Synthetic Bagdad: {measure}", unit, shown, value, "2025", number, quote))
    for pid, quote in (("fcx-bagdad-reserve-life", "the reserve life exceeds 80 years"),
                       ("fcx-bagdad-decision", "The studies are updated before a decision during 2026."),
                       ("fcx-bagdad-timing", "three to four years to complete.")):
        passages.append({"id": pid, "source": source, "locator": {"paragraph": number, "quote": quote}})
    abra = ("Synthetic: an environmental impact statement is planned for the first half of 2026. The economics would "
            "be supported by an incentive copper price of less than $4.00 per pound.")
    number = page.p(abra)
    figures.append(_prose("fcx-el-abra-incentive-2025", source, "Synthetic El Abra incentive price (less than)", lb,
                          "$4.00", "4.00", "2025", number, "incentive copper price of less than $4.00 per pound"))
    passages.append({"id": "fcx-el-abra-permitting", "source": source, "locator": {
        "paragraph": number, "quote": "an environmental impact statement is planned for the first half of 2026."}})
    addition = "Synthetic: the project could add over 700 million pounds of copper per year."
    figures.append(_prose("fcx-el-abra-addition-2025", source, "Synthetic El Abra addition (more than)",
                          "mlb_per_year", "700", "700", "2025", page.p(addition), addition))
    ptfi = "Synthetic: PTFI sales are expected to approximate 0.9 billion pounds of copper for the year 2026."
    figures.append(_prose("fcx-ptfi-sales-guidance-2026", source, "Synthetic expected PTFI sales", "blb", "0.9", "0.9",
                          "2026", page.p(ptfi), ptfi))
    return page, figures, passages


def fcx_2024() -> tuple[Page, list[dict], list[dict]]:
    page, source, figures = Page("Synthetic Producer A annual report, fiscal 2024"), "fcx-synthetic-2024", []
    text = "Synthetic: the expansion would require an incentive copper price in the range of $3.50 to $4.00 per pound."
    number = page.p(text)
    quote = "an incentive copper price in the range of $3.50 to $4.00 per pound"
    figures.append(_prose("fcx-bagdad-incentive-low-2024", source, "Synthetic Bagdad range, first value",
                          "usd_per_lb", "$3.50", "3.50", "2024", number, quote))
    figures.append(_prose("fcx-bagdad-incentive-high-2024", source, "Synthetic Bagdad range, second value",
                          "usd_per_lb", "$4.00", "4.00", "2024", number, quote))
    ptfi = "Synthetic: PTFI sales are expected to approximate 1.55 billion pounds of copper in 2025."
    figures.append(_prose("fcx-ptfi-sales-guidance-2025", source, "Synthetic expected PTFI sales (earlier filing)",
                          "blb", "1.55", "1.55", "2025", page.p(ptfi), ptfi))
    return page, figures, []


def scco_2025() -> tuple[Page, list[dict], list[dict]]:
    page, source, figures, passages = Page("Synthetic Producer B annual report, fiscal 2025"), "scco-synthetic-2025", [], []
    header = page.row("Synthetic table", "2025", "2024")[1]
    for fid, label, cells, shown, value, unit in (
            ("scco-produced-2025", "Total pounds of copper produced", ["2,035.6", "2,057.7"], "2,035.6", "2035.6",
             "mlb"),
            ("scco-cost-before-2025", "Operating cash cost per pound before by-product revenues",
             ["$", "2.17", "$", "2.13"], "2.17", "2.17", "usd_per_lb"),
            ("scco-by-products-2025", "By-products per pound revenues", ["$", "(1.59)", "$", "(1.25)"], "(1.59)",
             "-1.59", "usd_per_lb"),
            ("scco-cost-net-2025", "Operating cash cost per pound net of by-product revenues",
             ["$", "0.58", "$", "0.89"], "0.58", "0.58", "usd_per_lb")):
        numbers = page.row(label, *cells)
        cell = [n for n, text in zip(numbers[1:], cells) if text != "$"][0]
        figures.append(_cell(fid, source, f"Synthetic Producer B: {fid}", unit, shown, value, "2025", header,
                             numbers[0], 1, cell, label, "2025"))
    for pid, text in (("scco-denominator", "Synthetic: costs are divided by total pounds of copper produced by our own "
                                           "mines."),
                      ("scco-scope", "Synthetic: costs are cost of sales without depreciation plus selling charges."),
                      ("scco-credits", "Synthetic: we credit against our costs the revenues of all by-products."),
                      ("scco-exclusions", "Synthetic: workers' participation and royalties are excluded.")):
        passages.append({"id": pid, "source": source, "locator": {"paragraph": page.p(text), "quote": text}})
    tia = "Synthetic: this greenfield project has a capacity of 120,000 tonnes of copper cathodes per year."
    number = page.p(tia)
    figures.append(_prose("scco-tia-maria-capacity-2025", source, "Synthetic Tia Maria capacity", "t_per_year",
                          "120,000", "120000", "2025", number, "a capacity of 120,000 tonnes of copper cathodes per "
                                                               "year"))
    passages.append({"id": "scco-tia-maria-greenfield", "source": source,
                     "locator": {"paragraph": number, "quote": "this greenfield project"}})
    budget = "Synthetic: the project budget has been set at $1,805 million."
    figures.append(_prose("scco-tia-maria-budget-2025", source, "Synthetic Tia Maria budget", "usd_million", "$1,805",
                          "1805", "2025", page.p(budget), budget))
    for pid, text in (("scco-tia-maria-history", "Synthetic: acquired in 2003; construction permit granted in 2019."),
                      ("scco-tia-maria-progress", "Synthetic: progress stood at 24% at the end of 2025."),
                      ("scco-tia-maria-start", "Synthetic: operations are planned to start in 2027.")):
        passages.append({"id": pid, "source": source, "locator": {"paragraph": page.p(text), "quote": text}})
    chancas = ("Synthetic: this greenfield project is expected to produce 130,000 tonnes of copper and 7,500 tonnes of "
               "molybdenum annually. The estimated capital investment is $2,600 million and operation is expected to "
               "begin in 2031.")
    number = page.p(chancas)
    for fid, shown, value, unit, quote, measure in (
            ("scco-los-chancas-copper-2025", "130,000", "130000", "t_per_year", "130,000 tonnes of copper",
             "expected copper production"),
            ("scco-los-chancas-molybdenum-2025", "7,500", "7500", "t_per_year", "7,500 tonnes of molybdenum",
             "expected molybdenum production"),
            ("scco-los-chancas-capital-2025", "$2,600", "2600", "usd_million", "investment is $2,600 million",
             "estimated capital investment")):
        figures.append(_prose(fid, source, f"Synthetic Los Chancas: {measure}", unit, shown, value, "2025", number,
                              quote))
    for pid, quote in (("scco-los-chancas-greenfield", "this greenfield project"),
                       ("scco-los-chancas-start", "operation is expected to begin in 2031.")):
        passages.append({"id": pid, "source": source, "locator": {"paragraph": number, "quote": quote}})
    blocked = "Synthetic: the project has not advanced because others occupy the area."
    passages.append({"id": "scco-los-chancas-blocked", "source": source,
                     "locator": {"paragraph": page.p(blocked), "quote": blocked}})
    michi = ("Synthetic: acquired in 2018, with inferred resources only, the project would produce 225,000 tonnes of "
             "copper per year for an investment of approximately $2.5 billion, with start-up by 2032.")
    number = page.p(michi)
    figures.append(_prose("scco-michiquillay-capacity-2025", source, "Synthetic Michiquillay capacity", "t_per_year",
                          "225,000", "225000", "2025", number, "produce 225,000 tonnes of copper per year"))
    figures.append(_prose("scco-michiquillay-capital-2025", source, "Synthetic Michiquillay investment",
                          "usd_billion", "$2.5", "2.5", "2025", number, "investment of approximately $2.5 billion"))
    for pid, quote in (("scco-michiquillay-acquired", "acquired in 2018"),
                       ("scco-michiquillay-resources", "with inferred resources only"),
                       ("scco-michiquillay-start", "with start-up by 2032.")):
        passages.append({"id": pid, "source": source, "locator": {"paragraph": number, "quote": quote}})
    guidance = "Synthetic: in 2026 we expect copper production to stand at 911,400 tonnes."
    figures.append(_prose("scco-production-guidance-2026", source, "Synthetic expected production", "t", "911,400",
                          "911400", "2026", page.p(guidance), guidance))
    return page, figures, passages


def scco_2024() -> tuple[Page, list[dict], list[dict]]:
    page, source, figures = Page("Synthetic Producer B annual report, fiscal 2024"), "scco-synthetic-2024", []
    budget = "Synthetic: the new project budget has been set at $1,802 million."
    figures.append(_prose("scco-tia-maria-budget-2024", source, "Synthetic Tia Maria budget (earlier filing)",
                          "usd_million", "$1,802", "1802", "2024", page.p(budget), budget))
    guidance = "Synthetic: in 2025 we expect copper production to reach 965,800 tonnes."
    figures.append(_prose("scco-production-guidance-2025", source, "Synthetic expected production (earlier filing)",
                          "t", "965,800", "965800", "2025", page.p(guidance), guidance))
    return page, figures, []


PAGES = {"fcx-synthetic-2025": fcx_2025, "fcx-synthetic-2024": fcx_2024, "scco-synthetic-2025": scco_2025,
         "scco-synthetic-2024": scco_2024}
SOURCES = {  # folder -> (file name, kind, origin, attempt, publisher, title, edition, edition date)
    "iea-synthetic": ("dataset.xlsx", "xlsx", "owner_download", 1, "Synthetic IEA",
                      "Synthetic critical minerals dataset", "2026", "2026-07-01"),
    "fcx-synthetic-2025": ("10k.htm", "html", "get", 1, "Synthetic Producer A", "Synthetic annual report, fiscal 2025",
                           "Fiscal 2025", "2026-02-13"),
    "fcx-synthetic-2024": ("10k.htm", "html", "get", 2, "Synthetic Producer A", "Synthetic annual report, fiscal 2024",
                           "Fiscal 2024", "2025-02-14"),
    "scco-synthetic-2025": ("10k.htm", "html", "get", 3, "Synthetic Producer B", "Synthetic annual report, fiscal 2025",
                            "Fiscal 2025", "2026-02-27"),
    "scco-synthetic-2024": ("10k.htm", "html", "get", 4, "Synthetic Producer B", "Synthetic annual report, fiscal 2024",
                            "Fiscal 2024", "2025-03-03"),
}


def source_bytes(folder: str) -> bytes:
    if folder == "iea-synthetic":
        return thesis_fakes.workbook(iea_sheets())
    return PAGES[folder]()[0].html()


def _approval(folder: str) -> str:
    return OWNER_APPROVAL if SOURCES[folder][2] == "owner_download" else GET_APPROVAL


def _url(folder: str) -> str:
    return f"https://example.org/synthetic-copper-tools/{folder}/{SOURCES[folder][0]}"


def _retrieved_at(folder: str) -> str:
    return f"2026-11-05T0{8 if SOURCES[folder][2] == 'owner_download' else 9}:0{SOURCES[folder][3]}:00+00:00"


def record_path(root: Path, folder: str) -> Path:
    return root / "acquisitions" / _approval(folder) / f"outcome-{SOURCES[folder][3]}.json"


def outcome(folder: str, data: bytes) -> dict:
    name, kind, origin, attempt = SOURCES[folder][:4]
    record = {"approval_id": _approval(folder), "n": attempt, "url": _url(folder), "kind": kind,
              "outcome": "complete", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "retained": f"{RETAINED}/{folder}/{name}"}
    if origin == "owner_download":
        return {**record, "origin": "owner_download", "http_status": None, "hash_kind": "owner_file",
                "recorded_at": _retrieved_at(folder)}
    return {**record, "http_status": 200, "body_state": "fully_read", "hash_kind": "complete_response",
            "body_completed_at": _retrieved_at(folder)}


def retain(root: Path, folder: str, data: bytes) -> None:
    """Retain ``data`` as the folder's file and record it, so it verifies under its new SHA-256."""
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / SOURCES[folder][0]).write_bytes(data)
    path = record_path(root, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(outcome(folder, data), indent=1) + "\n", encoding="utf-8", newline="\n")


def write_sources(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for folder in SOURCES:
        retain(root, folder, source_bytes(folder))
    return root


def source_entries(root: Path) -> list[dict]:
    entries = []
    for folder, (name, kind, origin, attempt, publisher, title, edition, edition_date) in SOURCES.items():
        record = json.loads(record_path(root, folder).read_text(encoding="utf-8"))
        entries.append({"id": folder, "kind": kind, "origin": origin, "publisher": publisher, "title": title,
                        "series": f"synthetic-{folder.rsplit('-', 1)[0]}", "edition": edition,
                        "edition_date": edition_date, "url": _url(folder), "approval_id": _approval(folder),
                        "attempt": attempt, "folder": folder, "name": name, "sha256": record["sha256"],
                        "bytes": record["bytes"], "retrieved_at": _retrieved_at(folder), "terms": dict(TERMS),
                        "transcription": None, "encoding": None})
    return entries


# ---------------------------------------------------------------- the synthetic catalogue

def _xlsx(figure_id, sheet, cell, label_cell, label, year, scenario, checks, measure):
    sheets = iea_sheets()
    value = sheets[sheet][cell]
    return {"id": figure_id, "source": "iea-synthetic", "measure": measure, "unit": "kt", "value": value,
            "as_shown": _grouped(value), "year": year, "basis": None, "scenario": scenario,
            "locator": {"sheet": sheet, "cell": cell, "label_cell": label_cell, "label": label},
            "checks": [{"cell": ref, "text": sheets[sheet][ref]} for ref in checks]}


def iea_figures() -> list[dict]:
    out = []
    for line, (row, label) in LINES.items():
        for (scenario, year), column in COLUMNS.items():
            figure = f"iea-demand-{line}-2025" if scenario is None else f"iea-demand-{line}-{scenario}-{year}"
            checks = [f"{column}5", "A7", "A2"] + ([f"{HEADS[scenario]}4"] if scenario else [])
            out.append(_xlsx(figure, S1, f"{column}{row}", f"A{row}", label, year,
                             SCENARIOS[scenario] if scenario else None, checks, f"Synthetic demand: {label}"))
    for country, (row, label) in COUNTRIES.items():
        for index, year in enumerate(SUPPLY_YEARS):
            out.append(_xlsx(f"iea-mine-{country}-{year}", S2, f"{MINE_COLUMNS[index]}{row}", f"A{row}", label, year,
                             "base case", [f"{MINE_COLUMNS[index]}4", "A6", "A2"], f"Synthetic mining: {label}"))
    for index, year in enumerate(SUPPLY_YEARS):
        out.append(_xlsx(f"iea-refining-total-{year}", S2, f"{REFINING_COLUMNS[index]}14", "G14", "Total", year,
                         "base case", [f"{REFINING_COLUMNS[index]}4", "G6", "A2"], "Synthetic refining: Total"))
    for (scenario, year) in DC:
        column = COLUMNS[(scenario, year)]
        figure = "iea-networks-dc-2025" if scenario is None else f"iea-networks-dc-{scenario}-{year}"
        checks = [f"{column}5", "A11", "A2"] + ([f"{HEADS[scenario]}4"] if scenario else [])
        out.append(_xlsx(figure, S45, f"{column}12", "A12", "Copper", year, SCENARIOS[scenario] if scenario else None,
                         checks, "Synthetic networks, DC technology case"))
    return out


COVERAGE_PRODUCER_FIGURES = ("fcx-ptfi-sales-guidance-2025", "fcx-ptfi-sales-guidance-2026",
                             "scco-production-guidance-2025", "scco-production-guidance-2026")


def catalog(root: Path, part: str = "all") -> dict:
    """The SYNTHETIC inputs catalogue for the files under ``root``: ``part`` "coverage" holds only what the coverage
    calculator reads (the IEA figures, the two notes and the four reference-magnitude figures); "all" adds the
    producer comparison's figures and passages."""
    figures, passages = iea_figures(), [
        {"id": "iea-supply-note-pipeline", "source": "iea-synthetic",
         "locator": {"sheet": S2, "cell": "A72", "text": NOTE_PIPELINE}},
        {"id": "iea-supply-note-base-case", "source": "iea-synthetic",
         "locator": {"sheet": S2, "cell": "A73", "text": NOTE_BASE}}]
    for build in PAGES.values():
        _, more_figures, more_passages = build()
        figures += [f for f in more_figures if part == "all" or f["id"] in COVERAGE_PRODUCER_FIGURES]
        passages += more_passages if part == "all" else []
    return {"catalog_version": "copper-inputs-0.1", "id": "copper-coverage", "prepared_on": "2026-11-05",
            "sources": source_entries(root), "figures": figures, "passages": passages}


def write_catalog(folder: Path, catalog_: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inputs.json").write_text(json.dumps(catalog_, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                        newline="\n")
    return folder

"""The published producer unit-cost comparison, the company-stated projects and the capital-recovery panel
(copper-producers-0.2). Pure functions over the verified catalogue values and, for Bagdad's later statement, the
verified FCX records copper_linked reads; nothing here reads a file or a network.

Two producers' disclosed unit costs are shown side by side for 2025 with what makes them not comparable (the
comparability matrix). They are not a cost curve, do not identify a marginal mine and give no industry incentive price.
Each row reconciles exactly (before credits + credits + the other charges = the stated unit net cash cost) or is
withheld. A cash margin (E12) is shown only where the company's own revenue per pound for the same division and year is
retained, and it is a difference of reported division averages: not any mine's avoidable cost, so it says nothing about
whether output is, or is not, at risk of closing.

Projects: each company-stated capacity, capital, timing and incentive price, with capital per tonne of annual capacity
(E13, k = K / Q in US dollars per t/yr, whole dollars) where both are stated. The k values are not comparable between
a brownfield expansion and greenfield projects, and none is averaged or used as a default. Bagdad is two statements,
each its own row and computed on its own figures only: the company's later estimates (from the FCX records, first)
and the earlier 10-K statement (from the catalogue, unchanged). Break-even economics is its own field, never an
incentive price; the start of production is a passage, and the long-term annual rate is never placed in a year.

The capital-recovery panel (E14) has no defaults: for an entered rate r >= 0 (in percent) and a positive whole number
of years n, CRF(r, n) = r(1 + r)^n / ((1 + r)^n - 1) for r > 0 and CRF(0, n) = 1 / n (the formula's limit as r falls
to zero: the capital recovered evenly with no return), and the charge per pound is K x CRF / Q in pounds. Everything is
exact (Fraction) until it is shown. It ignores construction-period interest, ramp-up, sustaining capital, taxes and
closure; it never solves for a price, and it is not an incentive price. Its inputs are never stored.
"""
from decimal import Decimal
from fractions import Fraction
import re

from . import copper_linked
from .copper_coverage import POUND_KG, plain
from .thesis_rules import ThesisRefused

PRODUCERS_VERSION = "copper-producers-0.2"
LB_PER_TONNE = Fraction(1000) / Fraction(POUND_KG)  # About 2,204.6226 lb per tonne, kept as an exact fraction.
CRF_PLACES, CHARGE_PLACES, MARGIN_PLACES = 6, 3, 2
MAX_RATE_PCT, MAX_YEARS = Decimal(100), 100  # Input-size guards on the panel (and at most four decimals), not ranges.
_RATE = re.compile(r"\d{1,3}(?:\.\d{1,4})?", re.ASCII)
_YEARS = re.compile(r"[1-9]\d{0,2}", re.ASCII)
IGNORES = ("construction-period interest", "ramp-up to full capacity", "sustaining capital", "taxes and royalties",
           "closure costs")
TITLE = "Published producer unit-cost comparison"
CAN_ESTABLISH = ("For the year, each listed division's reported average revenue per pound exceeded its reported "
                 "average unit net cash cost (by-product method): a statement about one year's division averages, "
                 "each cost defined the company's way.")
CANNOT_ESTABLISH = (
    "Whether any mine is, or is not, at risk of closing. The test for a mine already built is whether price covers its "
    "avoidable cost, what it would stop paying if it stopped producing. These figures are not that cost: they average "
    "several mines, so the spread between mines is hidden; they follow each company's own definition, leaving some "
    "cash items out and including some costs that would not stop at once; they exclude sustaining capital; and their "
    "by-product credits move with other metals' prices.",
    "Whether new supply gets built. A new mine must also cover sustaining capital, recover its initial capital with a "
    "return, and pay taxes and royalties, all spent years before its first tonne.",
    "The industry's marginal cost: these are averages of large, long-life operations rich in by-products, not a "
    "sample of the industry.",
    "An industry incentive price.",
    "Anything about how the companies' shares behave.")
BROWNFIELD_GREENFIELD = ("A brownfield expansion uses an existing mine's permits, infrastructure and known ore, so "
                         "its stated build time is short; the greenfield timelines in these filings run over many "
                         "years, shaped by community agreements, water, power and security as much as by "
                         "construction. Capital per tonne of annual capacity is therefore not comparable between "
                         "them, and none is averaged or used as a default.")
CAPACITY_LABEL = "incremental, long-term annual rate"
NOTE_INCENTIVE = ("The company used 'incentive copper price' in its 10-Ks and 'break-even economics' in the approval "
                  "release. Neither term is defined in these documents; this project does not treat them as the same "
                  "figure or derive one from the other.")
NOTE_NO_PATH = ("The company gives a first production target and a long-term annual rate, but no year-by-year path; "
                "nothing between them is shown or assumed.")
# Fields every project carries; an entry that does not list one gets this empty value.
EMPTY = {"capacity_label": None, "break_even": [], "break_even_condition": None, "construction": None, "caveats": [],
         "statement": None, "earlier_capital": None, "by_product": None}

# A cost row: its figures in order, each with its role; "before" + "credits" + every "other" = "net" exactly.
ROWS = (
    {"id": "fcx-us", "producer": "Freeport-McMoRan", "division": "U.S. copper mines",
     "method": "By-product method, per pound of copper (shown with copper sales in recoverable pounds)",
     "before": "fcx-us-site-costs-2025", "credits": ["fcx-us-credits-2025"], "other": ["fcx-us-treatment-2025"],
     "net": "fcx-us-unit-net-2025", "co_product": "fcx-us-co-product-2025", "revenue": "fcx-us-revenue-2025",
     "gross_profit": "fcx-us-gross-profit-2025", "volume": "fcx-us-sales-2025"},
    {"id": "fcx-south-america", "producer": "Freeport-McMoRan", "division": "South America operations",
     "method": "By-product method, per pound of copper (shown with copper sales in recoverable pounds)",
     "before": "fcx-sa-site-costs-2025", "credits": ["fcx-sa-credits-2025"],
     "other": ["fcx-sa-treatment-2025", "fcx-sa-royalty-2025"], "net": "fcx-sa-unit-net-2025",
     "co_product": "fcx-sa-co-product-2025", "revenue": "fcx-sa-revenue-2025",
     "gross_profit": "fcx-sa-gross-profit-2025", "volume": "fcx-sa-sales-2025"},
    {"id": "fcx-indonesia", "producer": "Freeport-McMoRan", "division": "Indonesia (PTFI)",
     "method": "By-product method, per pound of copper (shown with copper sales in recoverable pounds)",
     "before": "fcx-id-site-costs-2025", "credits": ["fcx-id-credits-2025"],
     "other": ["fcx-id-treatment-2025", "fcx-id-export-duties-2025", "fcx-id-royalty-2025"],
     "net": "fcx-id-unit-net-2025", "co_product": "fcx-id-co-product-2025", "revenue": "fcx-id-revenue-2025",
     "gross_profit": "fcx-id-gross-profit-2025", "volume": "fcx-id-sales-2025"},
    {"id": "fcx-consolidated", "producer": "Freeport-McMoRan", "division": "Consolidated",
     "method": "By-product method, per pound of copper; excludes the stated idle-facility and recovery costs",
     "before": "fcx-site-costs-2025", "credits": [], "other": [], "net": "fcx-unit-net-2025", "co_product": None,
     "revenue": "fcx-realized-price-2025", "gross_profit": None, "volume": "fcx-sales-2025",
     "excluded": "fcx-mud-rush-2025"},
    {"id": "scco", "producer": "Southern Copper", "division": "Consolidated (Peru and Mexico)",
     "method": "Southern Copper's own definition, per pound of copper produced by its own mines",
     "before": "scco-cost-before-2025", "credits": ["scco-by-products-2025"], "other": [], "net": "scco-cost-net-2025",
     "co_product": None, "revenue": None, "gross_profit": None, "volume": "scco-produced-2025"},
)
MARGIN_ROWS = ("fcx-us", "fcx-south-america", "fcx-indonesia")  # Divisions with their own revenue per pound retained.
SCCO_MARGIN = ("Withheld: Southern Copper's revenue per pound of copper is not among the retained figures, and "
               "exchange prices quoted in its filing are not used in its place.")

# The comparability matrix: fixed text stating no figures (the figures are in the rows), each row citing what it rests on.
MATRIX = (
    {"dimension": "Period", "fcx": "Calendar year", "scco": "Calendar year", "comparable": "yes", "cites": []},
    {"dimension": "Currency and unit", "fcx": "US dollars per pound of copper", "scco": "US dollars per pound of copper",
     "comparable": "yes", "cites": []},
    {"dimension": "Denominator", "fcx": "Unit costs shown with copper sales in recoverable pounds",
     "scco": "Pounds of copper produced by its own mines", "comparable": "no",
     "cites": ["fcx-sales-label", "scco-denominator"]},
    {"dimension": "Geography", "fcx": "U.S., South America and Indonesia divisions, and consolidated",
     "scco": "Peru and Mexico, consolidated only", "comparable": "no", "cites": []},
    {"dimension": "By-product treatment",
     "fcx": "By-product method (other metals credited against costs) and co-product method (shared costs allocated by "
            "revenue)",
     "scco": "Credits the revenues of all by-products and net revenue on metal bought from third parties; no "
             "co-product figure", "comparable": "partly: only the figures before credits are near in concept",
     "cites": ["fcx-by-product-method", "fcx-co-product-method", "scco-credits"]},
    {"dimension": "Scope of costs",
     "fcx": "Site production and delivery, treatment charges, royalties and export duties; excludes depreciation, "
            "noncash items and the stated idle-facility costs",
     "scco": "Cost of sales without depreciation, plus selling and administrative costs and treatment charges; excludes "
             "workers' participation, royalties, exploration and non-recurring items", "comparable": "no",
     "cites": ["scco-scope", "scco-exclusions"]},
    {"dimension": "Integration", "fcx": "Partly integrated; some divisions pay treatment charges",
     "scco": "Smelts and refines its own concentrate", "comparable": "no", "cites": []},
    {"dimension": "Credits move with other metals", "fcx": "Yes: gold, molybdenum and silver",
     "scco": "Yes: molybdenum, silver, zinc and others", "comparable": "no",
     "cites": ["fcx-by-product-method", "scco-credits"]},
)

PROJECTS = (
    # Bagdad's later statement: every id here is a record of the FCX research (copper_linked), none is in the catalogue.
    {"id": "bagdad-2026-11-04", "name": "Bagdad expansion", "company": "Freeport-McMoRan", "type": "brownfield",
     "type_text": "Brownfield: an expansion of an existing mine", "capacity": ["nr-bagdad-cu-increment"],
     "capacity_unit": "mlb_per_year", "capacity_label": CAPACITY_LABEL, "capital": "nr-bagdad-capex-estimate",
     "incentive": [], "break_even": ["nr-bagdad-breakeven-cu"], "break_even_condition": "nr-bagdad-breakeven-mo",
     "construction": "nr-bagdad-construction-years",
     "passages": ["nr-p-board-approval", "q3-p-bagdad-approval", "nr-p-schedule"],
     "caveats": ["nr-p-cost-risk", "nr-p-estimates-change"],
     "statement": {"kind": "company_estimates", "source_of": "nr-bagdad-capex-estimate"}},
    # Bagdad's earlier statement, the fiscal 2025 10-K: unchanged figures and passages from the catalogue.
    {"id": "bagdad", "name": "Bagdad expansion", "company": "Freeport-McMoRan", "type": "brownfield",
     "type_text": "Brownfield: an expansion of an existing mine", "capacity": ["fcx-bagdad-low-2025",
                                                                             "fcx-bagdad-high-2025"],
     "capacity_unit": "mlb_per_year", "capital": "fcx-bagdad-capital-2025",
     "incentive": ["fcx-bagdad-incentive-2025", "fcx-bagdad-incentive-low-2024", "fcx-bagdad-incentive-high-2024"],
     "passages": ["fcx-bagdad-since", "fcx-bagdad-reserve-life", "fcx-bagdad-decision", "fcx-bagdad-timing"],
     "statement": {"kind": "earlier_statement", "source_of": "fcx-bagdad-capital-2025"}},
    {"id": "el-abra", "name": "El Abra mill project", "company": "Freeport-McMoRan", "type": "brownfield",
     "type_text": "A large mill at an existing operation", "capacity": ["fcx-el-abra-addition-2025"],
     "capacity_unit": "mlb_per_year", "capital": None, "incentive": ["fcx-el-abra-incentive-2025"],
     "passages": ["fcx-el-abra-permitting"]},
    {"id": "tia-maria", "name": "Tia Maria", "company": "Southern Copper", "type": "greenfield",
     "type_text": "Greenfield: a new mine", "capacity": ["scco-tia-maria-capacity-2025"], "capacity_unit": "t_per_year",
     "capital": "scco-tia-maria-budget-2025", "incentive": [], "earlier_capital": "scco-tia-maria-budget-2024",
     "passages": ["scco-tia-maria-greenfield", "scco-tia-maria-history", "scco-tia-maria-progress",
                  "scco-tia-maria-start"]},
    {"id": "los-chancas", "name": "Los Chancas", "company": "Southern Copper", "type": "greenfield",
     "type_text": "Greenfield: a new mine", "capacity": ["scco-los-chancas-copper-2025"], "capacity_unit": "t_per_year",
     "capital": "scco-los-chancas-capital-2025", "incentive": [], "by_product": "scco-los-chancas-molybdenum-2025",
     "passages": ["scco-los-chancas-greenfield", "scco-los-chancas-start", "scco-los-chancas-blocked"]},
    {"id": "michiquillay", "name": "Michiquillay", "company": "Southern Copper", "type": "greenfield",
     "type_text": "Greenfield: a new mine", "capacity": ["scco-michiquillay-capacity-2025"],
     "capacity_unit": "t_per_year", "capital": "scco-michiquillay-capital-2025", "incentive": [],
     "passages": ["scco-michiquillay-acquired", "scco-michiquillay-resources", "scco-michiquillay-start"]},
)
CAPITAL_UNITS = {"nr-bagdad-capex-estimate": Fraction(10) ** 9, "fcx-bagdad-capital-2025": Fraction(10) ** 9, "scco-tia-maria-budget-2025": Fraction(10) ** 6,
                 "scco-los-chancas-capital-2025": Fraction(10) ** 6, "scco-michiquillay-capital-2025": Fraction(10) ** 9}


LINKED_IDS = set(copper_linked.FIGURES) | set(copper_linked.PASSAGES)


def figure_ids() -> set[str]:
    """The catalogue figures the comparison reads (never a linked FCX record)."""
    ids = set()
    for row in ROWS:
        ids |= {row["before"], row["net"], row["volume"], *row["credits"], *row["other"]}
        ids |= {row[key] for key in ("co_product", "revenue", "gross_profit", "excluded") if row.get(key)}
    for project in PROJECTS:
        ids |= {*project["capacity"], *project["incentive"]}
        ids |= {project[key] for key in ("capital", "earlier_capital", "by_product") if project.get(key)}
    return ids - LINKED_IDS


def passage_ids() -> set[str]:
    return ({cite for row in MATRIX for cite in row["cites"]} | {cite for project in PROJECTS
                                                                  for cite in project["passages"]}) - LINKED_IDS


# ---------------------------------------------------------------- exact display

def half_even(value: Fraction, places: int) -> str:
    """A Fraction rounded ROUND_HALF_EVEN to ``places`` decimals, comma-grouped, never "-0"."""
    scaled = value * 10 ** places
    whole = scaled.numerator // scaled.denominator
    rest = scaled - whole
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and whole % 2 == 1):
        whole += 1
    sign = "-" if whole < 0 else ""
    digits = str(abs(whole)).rjust(places + 1, "0")
    integer, fraction = digits[:len(digits) - places] if places else digits, digits[len(digits) - places:]
    grouped = f"{int(integer):,}"
    return sign + grouped + (f".{fraction}" if places else "")


def _take(values: dict[str, Decimal], ids: list[str]) -> tuple[list[Decimal] | None, list[str]]:
    missing = [figure for figure in ids if figure not in values]
    return (None, missing) if missing else ([values[figure] for figure in ids], [])


# ---------------------------------------------------------------- the cost rows and margins

def cost_rows(values: dict[str, Decimal]) -> list[dict]:
    """Each row with its state: available when every figure is verified and the row reconciles exactly (a row without
    credits or charges has nothing to reconcile), withheld otherwise; a withheld row's reason names figures, never
    values."""
    out = []
    for row in ROWS:
        ids = [row["before"], *row["credits"], *row["other"], row["net"]]
        found, missing = _take(values, ids)
        if found is None:
            state, reconciles = "withheld", None
        elif row["credits"] or row["other"]:
            reconciles = sum(found[:-1]) == found[-1]
            state = "available" if reconciles else "withheld"
        else:
            state, reconciles = "available", None
        out.append({"id": row["id"], "producer": row["producer"], "division": row["division"],
                    "method": row["method"], "figures": {key: row.get(key) for key in
                                                         ("before", "credits", "other", "net", "co_product", "revenue",
                                                          "gross_profit", "volume", "excluded")},
                    "state": state, "reconciles": reconciles, "withheld": missing,
                    "problem": None if state == "available" else
                    ("A figure it needs is not verified" if missing else
                     "Its figures do not reconcile: before credits, credits and charges do not add to the stated unit "
                     "net cash cost")})
    return out


def margins(values: dict[str, Decimal], rows: list[dict]) -> list[dict]:
    """E12, for the divisions whose own revenue per pound is retained, beside the company's own gross profit per pound
    (which also deducts depreciation and noncash items). Southern Copper's margin is withheld."""
    state = {row["id"]: row["state"] for row in rows}
    out = []
    for row in ROWS:
        if row["id"] not in MARGIN_ROWS:
            continue
        ids = [row["revenue"], row["net"]]
        found, missing = _take(values, ids)
        available = found is not None and state[row["id"]] == "available"
        margin = found[0] - found[1] if available else None
        out.append({"row": row["id"], "equation": "E12", "uses": ids, "withheld": missing,
                    "value": None if margin is None else plain(margin),
                    "shown": None if margin is None else half_even(Fraction(margin), MARGIN_PLACES),
                    "gross_profit": row["gross_profit"], "state": "available" if available else "withheld"})
    out.append({"row": "scco", "equation": "E12", "uses": [], "withheld": [], "value": None, "shown": None,
                "gross_profit": None, "state": "not_retained", "problem": SCCO_MARGIN})
    return out


# ---------------------------------------------------------------- projects and capital per annual tonne

def _tonnes_per_year(project: dict, capacity: Decimal) -> Fraction:
    if project["capacity_unit"] == "mlb_per_year":
        return Fraction(capacity) * 10 ** 6 / LB_PER_TONNE
    return Fraction(capacity)


def _pounds_per_year(project: dict, capacity: Decimal) -> Fraction:
    if project["capacity_unit"] == "mlb_per_year":
        return Fraction(capacity) * 10 ** 6
    return Fraction(capacity) * LB_PER_TONNE


def projects(values: dict[str, Decimal]) -> list[dict]:
    """The company-stated projects; k = K / Q (E13) per stated capacity end, where both are stated and verified."""
    out = []
    for project in PROJECTS:
        intensity = []
        if project["capital"] is not None:
            for capacity in project["capacity"]:
                found, missing = _take(values, [project["capital"], capacity])
                value = None
                if found is not None:
                    value = Fraction(found[0]) * CAPITAL_UNITS[project["capital"]] / _tonnes_per_year(project, found[1])
                intensity.append({"equation": "E13", "uses": [project["capital"], capacity], "withheld": missing,
                                  "shown": None if value is None else half_even(value, 0)})
        out.append({**{key: project.get(key, EMPTY.get(key)) for key in (
                        "id", "name", "company", "type", "type_text", "capacity", "capacity_unit", "capacity_label",
                        "capital", "incentive", "break_even", "break_even_condition", "construction", "earlier_capital",
                        "by_product", "passages", "caveats", "statement")},
                    "capital_per_annual_tonne": intensity,
                    "intensity_problem": None if project["capital"] is not None else
                    "Not computed: the company states no capital for this project"})
    return out


# ---------------------------------------------------------------- the capital-recovery panel (E14)

def _rate(value: object) -> Fraction:
    if not isinstance(value, str) or not _RATE.fullmatch(value) or Decimal(value) > MAX_RATE_PCT:
        raise ThesisRefused(422, "The rate is a percentage of at least 0 and at most 100 (for example \"8\" or "
                                 "\"7.5\"), with at most four decimal places; a negative rate is refused")
    return Fraction(Decimal(value)) / 100


def _years(value: object) -> int:
    if not isinstance(value, str) or not _YEARS.fullmatch(value) or int(value) > MAX_YEARS:
        raise ThesisRefused(422, f"The life is a positive whole number of years, at most {MAX_YEARS}; zero, a negative "
                                 "or a fractional life is refused")
    return int(value)


def crf(rate: Fraction, years: int) -> Fraction:
    """CRF(r, n) = r(1 + r)^n / ((1 + r)^n - 1) for r > 0; CRF(0, n) = 1 / n, the limit as r falls to zero."""
    if years < 1:
        raise ValueError("the life is at least one year")
    if rate < 0:
        raise ValueError("the rate is not negative")
    if rate == 0:
        return Fraction(1, years)
    growth = (1 + rate) ** years
    return rate * growth / (growth - 1)


def capital_charge(values: dict[str, Decimal], rate_pct: object, years: object) -> dict:
    """The E14 panel for an entered rate (percent) and life: the CRF and each project's capital charge per pound of
    stated capacity, exact until shown. Raises ThesisRefused (422) for an input outside the panel's rules."""
    rate, life = _rate(rate_pct), _years(years)
    factor = crf(rate, life)
    rows = []
    for project in PROJECTS:
        charges = []
        for capacity in project["capacity"]:
            if project["capital"] is None:
                break
            found, missing = _take(values, [project["capital"], capacity])
            value = None
            if found is not None:
                capital = Fraction(found[0]) * CAPITAL_UNITS[project["capital"]]
                pounds = _pounds_per_year(project, found[1])
                value = capital / (life * pounds) if rate == 0 else capital * factor / pounds
            charges.append({"equation": "E14", "uses": [project["capital"], capacity], "withheld": missing,
                            "shown": None if value is None else half_even(value, CHARGE_PLACES)})
        rows.append({"project": project["id"], "charges": charges,
                     "problem": None if project["capital"] is not None else
                     "Not computed: the company states no capital for this project"})
    return {"view_version": PRODUCERS_VERSION, "rate_pct": rate_pct, "years": life,
            "method": "limit_at_zero_rate" if rate == 0 else "annuity",
            "crf": half_even(factor, CRF_PLACES), "projects": rows, "ignores": list(IGNORES), "stored": False,
            "provider_called": False}


def comparison(values: dict[str, Decimal]) -> dict:
    """The producer part of the tools' view: the matrix, the rows, the margins, the projects and the empty panel."""
    rows = cost_rows(values)
    return {"version": PRODUCERS_VERSION, "title": TITLE, "matrix": [dict(row) for row in MATRIX], "rows": rows,
            "margins": margins(values, rows), "projects": projects(values),
            "capital_panel": {"rate_pct": None, "years": None, "ignores": list(IGNORES),
                              "rate_rule": "A percentage of at least 0 and at most 100, with at most four decimals",
                              "years_rule": f"A positive whole number of years, at most {MAX_YEARS}"},
            "can_establish": CAN_ESTABLISH, "cannot_establish": list(CANNOT_ESTABLISH),
            "brownfield_greenfield": BROWNFIELD_GREENFIELD,
            "notes": {"incentive_break_even": NOTE_INCENTIVE, "no_path": NOTE_NO_PATH}}

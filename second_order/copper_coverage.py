"""The copper coverage calculator (copper-coverage-0.1): world copper demand in the IEA Critical Minerals Dataset 2026
against the IEA's counted mine supply, with three controls and one-at-a-time perturbations. Pure functions over exact
Decimals; nothing here reads a file, writes, fetches or calls a model.

What it computes, and nothing more (the design's equations E1-E8):
- E1 R = D - M_c: demand not covered by the counted mine pipeline, for one year and one published scenario. It is a
  requirement on other sources (recycling, mines not yet counted, stocks, or lower demand), never a deficit, a
  shortage or a balance, and nothing here computes a gap or weeks of consumption.
- E2 r = R / D x 100, shown to one decimal (ROUND_HALF_EVEN).
- E3 the change in R since the dataset's base year 2025, decomposed into the change in each published demand row,
  the change in the published non-additivity terms and the change in counted mine supply.
- E4 D' = D_printed + the sum of (x'_k - x_k) over the changed components only: a total is never rebuilt from parts.
- E5 M' = M_c + dM, or M_c + the sum of (f_c - 1) M_c,c over the countries given a factor.
- E6 R' = D' - M'.
- E8 epsilon = the printed energy-technology total minus the sum of its printed components, and delta = the printed
  total demand minus (energy + other uses): the IEA's published non-additivity, shown and never redistributed.
E7 (recycling) is not in this version: recycling is not an input, and a request that names it is refused.

Inputs are the verified catalogue values only (copper_inputs.verified_values). Every output names the figures it uses;
when any of them is not verified the output has no value and lists them as withheld. Display rounding never feeds
later arithmetic: every computed value keeps its exact value beside the shown text.
"""
from decimal import Decimal, InvalidOperation, localcontext
import re

from .thesis_arithmetic import display, share_pct
from .thesis_rules import ThesisRefused

ENGINE_VERSION = "copper-coverage-0.1"
BASE_YEAR = "2025"
YEARS = ("2030", "2035", "2040")
SCENARIOS = {"cps": "Current Policies scenario", "steps": "Stated Policies scenario", "hd": "High Demand Scenario"}
COMPONENTS = {"solar": "Solar PV", "wind": "Wind", "other-low-emission": "Other low emissions power generation",
              "ev": "Electric vehicles", "grid-storage": "Grid battery storage", "networks": "Electricity networks",
              "hydrogen": "Hydrogen technologies"}
TOTALS = {"energy": "Total energy technologies", "other-uses": "Other uses", "total": "Total demand"}
LINES = {**COMPONENTS, **TOTALS}
COUNTRIES = {"chile": "Chile", "drc": "Democratic Republic of Congo", "peru": "Peru", "china": "China",
             "russia": "Russia", "us": "United States", "rest": "Rest of world"}
DC_SCENARIOS = ("steps", "hd")  # The published "Wider direct current (DC) technology development" case has no CPS values.
DC_LABEL = "Wider direct current (DC) technology development"
CONTROLS = ("ev", "networks", "mine")
CONTROL_COMPONENT = {"ev": "ev", "networks": "networks"}
EXACT_PLACES = 5  # A computed kt value with more decimals (only a pound conversion makes one) is shown to the tonne.
SHOWN_PLACES = 3
PCT_PLACES = 1
MAX_INPUT = 30
MAX_INPUT_PLACES = 10
POUND_KG = Decimal("0.45359237")  # Exact by definition; kt = million pounds x 0.45359237.
_PLAIN = re.compile(r"-?\d+(?:\.\d+)?", re.ASCII)
RECYCLING = re.compile(r"recycl|scrap|secondary", re.I)
RECYCLING_REFUSED = ("Recycling is not an input in this version: it is deferred until the IEA states which demand "
                     "basis its figures use. Nothing was computed or saved.")
FLAG_TEXT = {
    "hybrid": "Hybrid: a component comes from another published scenario than the total it is applied to. This is not "
              "an IEA scenario; the IEA scenarios move together, and their published totals are shown beside it.",
    "technology_case": "Published technology case: the networks value is the IEA's wider direct current (DC) "
                       "technology case for the same scenario, applied to the base-case total.",
    "user_value": "User value: a component was entered by the user, not taken from a publication.",
    "outside_published_spread": "Outside all three IEA scenarios: an entered value lies outside the range of the three "
                                "published scenario values for that row and year.",
    "reference_magnitude": "Reference magnitude used as an assumption: a company disclosure, converted to copper "
                           "tonnes, entered as a change in counted mine supply. It is not a projection.",
}

# The reference magnitudes beside the mine control: company disclosures, never defaults (copper_producers names them).
REFERENCES = {
    "ptfi-sales-change": {"label": "Freeport-McMoRan's change in PTFI expected copper sales (stated for 2025 a year "
                                   "earlier, against the expectation for 2026), converted from pounds",
                          "uses": ("fcx-ptfi-sales-guidance-2025", "fcx-ptfi-sales-guidance-2026")},
    "scco-guidance-change": {"label": "Southern Copper's change in expected copper production (stated for 2025, "
                                      "against the expectation for 2026)",
                             "uses": ("scco-production-guidance-2025", "scco-production-guidance-2026")},
}


# ---------------------------------------------------------------- figure ids (the catalogue holds exactly these)

def demand_id(line: str, scenario: str | None, year: str) -> str:
    return f"iea-demand-{line}-{BASE_YEAR}" if scenario is None else f"iea-demand-{line}-{scenario}-{year}"


def mine_id(country: str, year: str) -> str:
    return f"iea-mine-{country}-{year}"


def refining_id(year: str) -> str:
    return f"iea-refining-total-{year}"


def dc_id(scenario: str | None, year: str) -> str:
    return f"iea-networks-dc-{BASE_YEAR}" if scenario is None else f"iea-networks-dc-{scenario}-{year}"


NOTE_IDS = ("iea-supply-note-pipeline", "iea-supply-note-base-case")


def figure_ids() -> set[str]:
    ids = {demand_id(line, None, BASE_YEAR) for line in LINES}
    ids |= {demand_id(line, scenario, year) for line in LINES for scenario in SCENARIOS for year in YEARS}
    ids |= {mine_id(country, year) for country in [*COUNTRIES, "total"] for year in (BASE_YEAR, *YEARS)}
    ids |= {refining_id(year) for year in (BASE_YEAR, *YEARS)}
    ids |= {dc_id(None, BASE_YEAR)} | {dc_id(scenario, year) for scenario in DC_SCENARIOS for year in YEARS}
    return ids | {figure for reference in REFERENCES.values() for figure in reference["uses"]}


DEFINITIONS = {
    "engine_version": ENGINE_VERSION, "base_year": BASE_YEAR, "years": list(YEARS), "scenarios": SCENARIOS,
    "components": COMPONENTS, "totals": TOTALS, "countries": COUNTRIES, "dc_scenarios": list(DC_SCENARIOS),
    "equations": {"E1": "R = D - M_c", "E2": "r = R / D x 100, one decimal, half-even",
                  "E3": "dR = R_y - R_2025 = dD - dM_c", "E4": "D' = D_printed + sum over changed k of (x'_k - x_k)",
                  "E5": "M' = M_c + dM, or M_c + sum over c of (f_c - 1) M_c,c", "E6": "R' = D' - M'",
                  "E8": "epsilon = E_printed - sum of components; delta = D_printed - (E_printed + O_printed)",
                  "E10": "kt = million pounds x 0.45359237"},
    "display": {"exact_places": EXACT_PLACES, "shown_places": SHOWN_PLACES, "pct_places": PCT_PLACES},
    "flags": FLAG_TEXT, "references": {key: list(value["uses"]) for key, value in REFERENCES.items()},
}


# ---------------------------------------------------------------- exact values and how they are shown

def exact(value: Decimal) -> Decimal:
    """The same number without trailing fractional zeros (an integer keeps exponent 0, never "1.2E+4"; zero is
    never "-0")."""
    if value == 0:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 80
        return value.quantize(Decimal(1)) if value == value.to_integral_value() else value.normalize()


def plain(value: Decimal) -> str:
    return format(exact(value), "f")


def places(value: Decimal) -> int:
    return max(0, -exact(value).as_tuple().exponent)


def shown_kt(value: Decimal) -> tuple[str, bool]:
    """(the shown text, whether it is rounded): exact up to EXACT_PLACES decimals, else to the tonne, half-even."""
    count = places(value)
    return (display(value, count), False) if count <= EXACT_PLACES else (display(value, SHOWN_PLACES), True)


def kt_item(value: Decimal | None, uses: list[str], withheld: list[str], equation: str) -> dict:
    if value is None:
        return {"equation": equation, "uses": uses, "withheld": withheld, "value": None, "shown": None,
                "rounded": None}
    text, rounded = shown_kt(value)
    return {"equation": equation, "uses": uses, "withheld": [], "value": plain(value), "shown": text,
            "rounded": rounded}


def pct_item(part: Decimal | None, whole: Decimal | None, uses: list[str], withheld: list[str]) -> dict:
    if part is None or whole is None or whole <= 0:
        return {"equation": "E2", "uses": uses, "withheld": withheld, "value": None, "shown": None, "rounded": None}
    return {"equation": "E2", "uses": uses, "withheld": [], "value": None,
            "shown": display(share_pct(part, whole), PCT_PLACES), "rounded": True}


class _Values:
    """The verified values, with every lookup recorded so each output names what it used and what was missing."""

    def __init__(self, values: dict[str, Decimal]):
        self.values = values

    def take(self, ids: list[str]) -> tuple[list[Decimal] | None, list[str]]:
        missing = [figure for figure in ids if figure not in self.values]
        return (None, missing) if missing else ([self.values[figure] for figure in ids], [])


def _published(values: _Values, figure: str) -> dict:
    found, missing = values.take([figure])
    return {"figure": figure, "value": None if found is None else plain(found[0]), "withheld": missing}


def _computed(values: _Values, ids: list[str], equation: str, compute) -> tuple[Decimal | None, dict]:
    found, missing = values.take(ids)
    value = None if found is None else compute(*found)
    return value, kt_item(value, ids, missing, equation)


# ---------------------------------------------------------------- the published baseline and R

def _demand_ids(scenario: str | None, year: str) -> dict[str, str]:
    return {line: demand_id(line, scenario, year) for line in LINES}


def _epsilon(values: _Values, scenario: str | None, year: str) -> tuple[dict, dict]:
    ids = _demand_ids(scenario, year)
    component_ids = [ids[key] for key in COMPONENTS]
    _, epsilon = _computed(values, [ids["energy"], *component_ids], "E8", lambda energy, *parts: energy - sum(parts))
    _, delta = _computed(values, [ids["total"], ids["energy"], ids["other-uses"]], "E8",
                         lambda total, energy, other: total - (energy + other))
    return epsilon, delta


def coverage_at(values: _Values, scenario: str | None, year: str) -> dict:
    """D, M_c, R and r for one year (scenario None: the base year 2025)."""
    ids = _demand_ids(scenario, year)
    demand, mine = ids["total"], mine_id("total", year)
    r_value, r_item = _computed(values, [demand, mine], "E1", lambda d, m: d - m)
    found, missing = values.take([demand, mine])
    share = pct_item(r_value, None if found is None else found[0], [demand, mine], missing)
    return {"demand": _published(values, demand), "mine": _published(values, mine), "residual": r_item,
            "share_pct": share}


def _decomposition(values: _Values, scenario: str, year: str) -> dict:
    now, then = _demand_ids(scenario, year), _demand_ids(None, BASE_YEAR)
    rows = []
    for line in [*COMPONENTS, "energy", "other-uses", "total"]:
        _, item = _computed(values, [now[line], then[line]], "E3", lambda new, old: new - old)
        rows.append({"line": line, "change": item})
    eps_now, delta_now = _epsilon(values, scenario, year)
    eps_then, delta_then = _epsilon(values, None, BASE_YEAR)

    def change_of(new: dict, old: dict) -> dict:
        if new["value"] is None or old["value"] is None:
            return kt_item(None, new["uses"] + old["uses"], new["withheld"] + old["withheld"], "E3")
        return kt_item(Decimal(new["value"]) - Decimal(old["value"]), new["uses"] + old["uses"], [], "E3")
    _, mine = _computed(values, [mine_id("total", year), mine_id("total", BASE_YEAR)], "E3", lambda new, old: new - old)
    _, residual = _computed(values, [now["total"], mine_id("total", year), then["total"], mine_id("total", BASE_YEAR)],
                            "E3", lambda d1, m1, d0, m0: (d1 - m1) - (d0 - m0))
    return {"demand_rows": rows, "epsilon_change": change_of(eps_now, eps_then),
            "delta_change": change_of(delta_now, delta_then), "mine_change": mine, "residual_change": residual}


def baseline(verified: dict[str, Decimal], scenario: str, year: str) -> dict:
    """The published baseline for one year and scenario: every demand row, epsilon and delta, counted mine supply by
    country, the IEA base-case refining series apart, R, r, the change in R since 2025 and its decomposition, and the
    perturbations around it."""
    values = _Values(verified)
    _scenario_year(scenario, year)
    ids = _demand_ids(scenario, year)
    epsilon, delta = _epsilon(values, scenario, year)
    return {
        "scenario": scenario, "year": year,
        "demand": [{"line": line, **_published(values, ids[line])} for line in LINES],
        "epsilon": epsilon, "delta": delta,
        "mine": [{"country": country, **_published(values, mine_id(country, year))}
                 for country in [*COUNTRIES, "total"]],
        "refining": _published(values, refining_id(year)),
        "coverage": coverage_at(values, scenario, year),
        "base": coverage_at(values, None, BASE_YEAR),
        "decomposition": _decomposition(values, scenario, year),
        "perturbations": perturbations(verified, scenario, year),
    }


def base_year(verified: dict[str, Decimal]) -> dict:
    """The dataset's base year 2025 (a model base year, not an outturn): demand rows, epsilon, delta, mine, R, r."""
    values = _Values(verified)
    epsilon, delta = _epsilon(values, None, BASE_YEAR)
    return {"year": BASE_YEAR,
            "demand": [{"line": line, **_published(values, demand_id(line, None, BASE_YEAR))} for line in LINES],
            "epsilon": epsilon, "delta": delta,
            "mine": [{"country": country, **_published(values, mine_id(country, BASE_YEAR))}
                     for country in [*COUNTRIES, "total"]],
            "refining": _published(values, refining_id(BASE_YEAR)),
            "networks_dc": _published(values, dc_id(None, BASE_YEAR)),
            "coverage": coverage_at(values, None, BASE_YEAR)}


# ---------------------------------------------------------------- reference magnitudes and perturbations

def reference_magnitude(verified: dict[str, Decimal], key: str) -> tuple[Decimal | None, dict]:
    """A company disclosure as copper kt: PTFI's sales change (billion pounds x 1,000 x 0.45359237) or Southern
    Copper's guidance change (tonnes / 1,000). Labelled a reference magnitude: never a default or a projection."""
    reference = REFERENCES[key]
    if key == "ptfi-sales-change":
        compute = lambda earlier, later: (earlier - later) * 1000 * POUND_KG  # noqa: E731
    else:
        compute = lambda earlier, later: (earlier - later) / 1000  # noqa: E731
    value, item = _computed(_Values(verified), list(reference["uses"]), "E10" if key == "ptfi-sales-change" else "E5",
                            compute)
    return value, {"reference": key, "label": reference["label"], "magnitude": item}


def perturbations(verified: dict[str, Decimal], scenario: str, year: str, mine_change: Decimal | None = None) -> list:
    """One-at-a-time effects on R (kt) around the baseline, in a fixed order (EV copper, networks, the networks
    technology case, mine supply, the joint published totals) and never ranked: each row names its kind of range, and
    ranges of different kinds are not comparable. No probability is attached to any row."""
    values, rows = _Values(verified), []
    others = [key for key in SCENARIOS if key != scenario]
    for control in ("ev", "networks"):
        component, cases = CONTROL_COMPONENT[control], []
        for other in others:
            value, effect = _computed(values, [demand_id(component, other, year), demand_id(component, scenario, year)],
                                      "E4", lambda new, old: new - old)
            cases.append({"label": SCENARIOS[other], "scenario": other,
                          "value": _published(values, demand_id(component, other, year)), "effect": effect})
        rows.append({"control": control, "kind": "published_scenario_value", "cases": cases})
        if control == "networks" and scenario in DC_SCENARIOS:
            _, effect = _computed(values, [dc_id(scenario, year), demand_id("networks", scenario, year)], "E4",
                                  lambda new, old: new - old)
            rows.append({"control": "networks", "kind": "published_technology_case",
                         "cases": [{"label": DC_LABEL, "scenario": scenario,
                                    "value": _published(values, dc_id(scenario, year)), "effect": effect}]})
    cases = []
    for key in REFERENCES:
        magnitude, item = reference_magnitude(verified, key)
        lower = kt_item(None if magnitude is None else magnitude, item["magnitude"]["uses"],
                        item["magnitude"]["withheld"], "E6")
        higher = kt_item(None if magnitude is None else -magnitude, item["magnitude"]["uses"],
                         item["magnitude"]["withheld"], "E6")
        cases.append({"label": item["label"], "reference": key, "magnitude": item["magnitude"],
                      "effect_if_lower": lower, "effect_if_higher": higher})
    rows.append({"control": "mine", "kind": "reference_magnitude", "cases": cases})
    if mine_change is not None:
        rows.append({"control": "mine", "kind": "user_declared",
                     "cases": [{"label": "The entered change in counted mine supply", "effect":
                                kt_item(-mine_change, [mine_id("total", year)], [], "E6")}]})
    cases = []
    for other in others:
        _, effect = _computed(values, [demand_id("total", other, year), demand_id("total", scenario, year)], "E4",
                              lambda new, old: new - old)
        cases.append({"label": SCENARIOS[other], "scenario": other,
                      "value": _published(values, demand_id("total", other, year)), "effect": effect})
    rows.append({"control": "joint", "kind": "published_totals", "cases": cases})
    return rows


# ---------------------------------------------------------------- assumptions (the three controls)

def refused(message: str) -> ThesisRefused:
    return ThesisRefused(422, message)


def _scenario_year(scenario: object, year: object) -> None:
    if scenario not in SCENARIOS:
        raise refused(f"The scenario must be one of {', '.join(SCENARIOS)}")
    if year not in YEARS:
        raise refused(f"The year must be one of {', '.join(YEARS)}")


def _number(value: object, where: str, signed: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > MAX_INPUT or not _PLAIN.fullmatch(value):
        raise refused(f"{where} must be a plain decimal written as text (for example \"2146\" or \"0.9\")")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise refused(f"{where} must be a plain decimal") from None
    if places(number) > MAX_INPUT_PLACES:
        raise refused(f"{where} has more than {MAX_INPUT_PLACES} decimal places")
    if not signed and number < 0:
        raise refused(f"{where} cannot be negative")
    return number


def _keys(value: object, allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise refused(f"{where} must be an object")
    for key in value:
        if isinstance(key, str) and RECYCLING.search(key):
            raise refused(RECYCLING_REFUSED)
    extra = sorted(set(value) - allowed, key=str)
    if extra:
        raise refused(f"{where} has unknown fields: {', '.join(map(str, extra))}")
    return value


def normalise(assumptions: object, scenario: str) -> dict:
    """The assumptions in canonical form, refusing anything outside the three controls. ``None`` for a control means no
    adjustment. Recycling, in any field name, is refused."""
    raw = _keys(assumptions, set(CONTROLS), "The assumptions")
    out = {}
    for control in ("ev", "networks"):
        entry = raw.get(control)
        if entry is None:
            out[control] = None
            continue
        entry = _keys(entry, {"source", "scenario", "kt"}, f"The {control} control")
        source = entry.get("source")
        if source in ("scenario", "technology_case"):
            if "kt" in entry or entry.get("scenario") not in SCENARIOS:
                raise refused(f"The {control} control names a published value by its scenario only")
            if source == "technology_case" and (control != "networks" or entry["scenario"] not in DC_SCENARIOS):
                raise refused("The technology case exists for electricity networks under the Stated Policies and "
                              "High Demand scenarios only")
            out[control] = {"source": source, "scenario": entry["scenario"]}
        elif source == "value":
            if "scenario" in entry or "kt" not in entry:
                raise refused(f"The {control} control's entered value is given in kt only")
            out[control] = {"source": "value", "kt": plain(_number(entry["kt"], f"The {control} value"))}
        else:
            raise refused(f"The {control} control's source must be scenario, technology_case or value")
    entry = raw.get("mine")
    if entry is None:
        out["mine"] = None
    else:
        entry = _keys(entry, {"source", "kt", "reference", "factors"}, "The mine control")
        if entry.get("source") == "total":
            if "factors" in entry or "kt" not in entry:
                raise refused("A total mine adjustment is a signed change in kt")
            reference = entry.get("reference")
            if reference is not None and reference not in REFERENCES:
                raise refused(f"The reference must be one of {', '.join(REFERENCES)}")
            out["mine"] = {"source": "total", "kt": plain(_number(entry["kt"], "The mine change", signed=True)),
                           "reference": reference}
        elif entry.get("source") == "countries":
            if "kt" in entry or "reference" in entry:
                raise refused("A country adjustment is a factor per country")
            factors = _keys(entry.get("factors"), set(COUNTRIES), "The country factors")
            if not factors:
                raise refused("A country adjustment names at least one country")
            out["mine"] = {"source": "countries",
                           "factors": {country: plain(_number(factors[country], f"The factor for {country}"))
                                       for country in COUNTRIES if country in factors}}
        else:
            raise refused("The mine control's source must be total or countries")
    return out


def _component_choice(values: _Values, control: str, entry: dict | None, scenario: str, year: str) -> tuple:
    """(the chosen value or None when withheld, the figure ids used, flags, withheld ids) for EV or networks."""
    component = CONTROL_COMPONENT[control]
    base_figure = demand_id(component, scenario, year)
    if entry is None:
        return None, [], [], []
    if entry["source"] == "scenario":
        figure = demand_id(component, entry["scenario"], year)
        found, missing = values.take([figure, base_figure])
        flags = ["hybrid"] if entry["scenario"] != scenario else []
        return (None if found is None else found[0]), [figure, base_figure], flags, missing
    if entry["source"] == "technology_case":
        figure = dc_id(entry["scenario"], year)
        found, missing = values.take([figure, base_figure])
        flags = ["technology_case"] + (["hybrid"] if entry["scenario"] != scenario else [])
        return (None if found is None else found[0]), [figure, base_figure], flags, missing
    spread = [demand_id(component, key, year) for key in SCENARIOS]
    found, missing = values.take(spread)
    value = Decimal(entry["kt"])
    flags = ["user_value"]
    if found is not None and not min(found) <= value <= max(found):
        flags.append("outside_published_spread")
    return (value if found is not None else None), [base_figure, *[f for f in spread if f != base_figure]], flags, \
        missing


def assess(verified: dict[str, Decimal], scenario: str, year: str, assumptions: object) -> dict:
    """The baseline for (scenario, year) with the normalised assumptions applied: D', M', R', r', the change in R'
    since 2025, the flags, and the perturbations around the baseline (with the entered mine change as its own row)."""
    _scenario_year(scenario, year)
    chosen = normalise(assumptions, scenario)
    values = _Values(verified)
    demand_figure, mine_figure = demand_id("total", scenario, year), mine_id("total", year)
    uses, withheld, flags = [demand_figure, mine_figure], [], []
    found, missing = values.take([demand_figure, mine_figure])
    withheld += missing
    demand = mine = None if found is None else found[0]
    if found is not None:
        demand, mine = found
    for control in ("ev", "networks"):
        value, used, more_flags, missing = _component_choice(values, control, chosen[control], scenario, year)
        uses += [figure for figure in used if figure not in uses]
        withheld += [figure for figure in missing if figure not in withheld]
        flags += [flag for flag in more_flags if flag not in flags]
        if chosen[control] is not None and value is not None and demand is not None:
            demand += value - verified[demand_id(CONTROL_COMPONENT[control], scenario, year)]
    mine_change = None
    entry = chosen["mine"]
    if entry is not None and entry["source"] == "total":
        mine_change = Decimal(entry["kt"])
        if entry["reference"] is not None:
            magnitude, item = reference_magnitude(verified, entry["reference"])
            uses += [figure for figure in item["magnitude"]["uses"] if figure not in uses]
            if magnitude is None:
                withheld += [figure for figure in item["magnitude"]["withheld"] if figure not in withheld]
            elif abs(mine_change) != magnitude:
                raise refused("A mine change tagged with a reference magnitude must equal that magnitude exactly "
                              f"({plain(magnitude)} kt, either sign)")
            flags.append("reference_magnitude")
    elif entry is not None:
        country_ids = [mine_id(country, year) for country in entry["factors"]]
        uses += country_ids
        found, missing = values.take(country_ids)
        withheld += missing
        if found is not None:
            mine_change = sum((Decimal(entry["factors"][country]) - 1) * found[index]
                              for index, country in enumerate(entry["factors"]))
    if withheld:
        demand = mine = None
    elif mine_change is not None:
        mine += mine_change
        if mine < 0:
            raise refused("The adjusted counted mine supply would be negative")
    residual = None if demand is None else demand - mine
    base = coverage_at(values, None, BASE_YEAR)["residual"]
    change = None if residual is None or base["value"] is None else residual - Decimal(base["value"])
    base_uses = base["uses"]
    return {
        "scenario": scenario, "year": year, "assumptions": chosen,
        "flags": [{"id": flag, "text": FLAG_TEXT[flag]} for flag in FLAG_TEXT if flag in flags],
        "demand": kt_item(demand, uses, withheld, "E4"),
        "mine": kt_item(mine, uses, withheld, "E5"),
        "residual": kt_item(residual, uses, withheld, "E6"),
        "share_pct": pct_item(residual, demand, uses, withheld),
        "residual_change": kt_item(change, uses + base_uses, withheld + base["withheld"], "E3"),
        "mine_change": None if chosen["mine"] is None else kt_item(mine_change, uses, withheld, "E5"),
        "perturbations": perturbations(verified, scenario, year, mine_change if not withheld else None),
    }

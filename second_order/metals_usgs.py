"""Reader for the retained USGS Mineral Commodity Summaries 2026 data-release CSV (metals-usgs-0.3).

It reads no file: a later step verifies the file and passes its rows in. Every figure here is the file's own number, or
a share, rank or ratio computed from the file's stated world total; nothing is curated. A world table is the rows whose
section starts with "World". Shares exist only against a world total that is printed as a positive number; a withheld
or qualified figure ("W", ">2,000,000") is shown as printed and never replaced by a guess. A country printed as a dash
("—", which the design reads as zero) counts as zero when countries are ordered and summed, and gets no share itself.

A series named in UNIT_ISSUES has a unit that the file states in conflict with the printed USGS chapter. The chapter
is not a source this project verifies, so nothing is converted: the series carries the issue in words, its quantities
are not shown on the page, and no years figure is made from it. Its shares and order stay, since a share divides two
figures of the same column. The size of a result never withholds it: a valid ratio under one year reads "less than 1".
"""
from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
import re

ENGINE = "metals-usgs-0.3"  # 0.3: each net import reliance row carries its commodity
HEADER = ["MCS chapter", "Section", "Commodity", "Country", "Statistics", "Statistics_detail", "Unit", "Year", "Value",
          "Notes", "Is critical mineral 2025", "Other notes"]
CHAPTER_NAMES = [
    "ALUMINUM", "BAUXITE AND ALUMINA", "ANTIMONY", "ARSENIC", "BERYLLIUM", "BISMUTH", "CADMIUM", "CESIUM", "CHROMIUM",
    "COBALT", "COPPER", "GALLIUM", "GERMANIUM", "GOLD", "GRAPHITE (NATURAL)", "INDIUM", "IRON ORE", "LEAD", "LITHIUM",
    "MAGNESIUM METAL", "MANGANESE", "MERCURY", "MOLYBDENUM", "NICKEL", "NIOBIUM (COLUMBIUM)", "PLATINUM-GROUP METALS",
    "RARE EARTHS", "RARE EARTHS (Heavy)", "RHENIUM", "RUBIDIUM", "SCANDIUM", "SELENIUM", "SILICON", "SILVER", "TANTALUM",
    "TELLURIUM", "THALLIUM", "TIN", "TITANIUM AND TITANIUM DIOXIDE", "TITANIUM MINERAL CONCENTRATES", "TUNGSTEN",
    "VANADIUM", "YTTRIUM", "ZINC", "ZIRCONIUM AND HAFNIUM"]
YEARS_LABEL = "at the 2025 rate; not a depletion date"
YEARS_UNDER_ONE = "less than 1"  # The years figure when world reserves are under one year of world output.
# Known conflicts between this file's unit and the printed USGS chapter, by series id. Evidence: the vanadium chapter of
# Mineral Commodity Summaries 2026 (pubs.usgs.gov/periodicals/mcs2026/mcs2026-vanadium.pdf), page 2, heads its
# reserves column "thousand metric tons"; this file gives the same figures (world 21,000) in "metric tons". The chapter
# is not retained or verified here, so the conflict is shown in words and nothing is converted.
UNIT_ISSUES = {
    "vanadium/reserves/reserves/metric-tons/2025": (
        "Unit in doubt: the printed USGS chapter (Mineral Commodity Summaries 2026, vanadium, page 2) gives these "
        "reserves in thousand metric tons, while this data file labels them metric tons. The chapter is not a source "
        "this page verifies, so the quantities and the years of reserves are not shown. The shares do not depend on "
        "the unit."),
}
NUMBER = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
ROUNDED = re.compile(r"\s*[:,]\s*rounded\s*$", re.IGNORECASE)
DASH = "—"
WORLD, OTHER = "World total", "Other countries"
COLUMN = {name: index for index, name in enumerate(HEADER)}


class UsgsRefused(ValueError):
    """The rows are not the USGS data-release layout this reader understands."""


def chapter_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def display_name(name):
    return name.capitalize()


def number(printed):
    """The plain decimal of a printed figure, without commas, or None when it is not a plain number."""
    text = printed.strip()
    return text.replace(",", "") if NUMBER.match(text) else None


def _fraction(plain):
    return Fraction(Decimal(plain))


def _show(value, places):
    quotient = Decimal(value.numerator) / Decimal(value.denominator)
    return str(quotient.quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN))


def _percent(part, world):
    return _show(part / world * 100, 1)


def _base(detail):
    return ROUNDED.sub("", detail.strip()).strip()


def _cell(row):
    value = row[COLUMN["Value"]]
    return {"value": value, "number": number(value), "notes": row[COLUMN["Notes"]]}


def _printed(value):
    return "Printed as “" + value + "”"


def _series_of(chapter, rows):
    """The world-table series of one chapter, in file order of first row, with shares and concentration."""
    groups, order, problems = {}, [], {}
    for row in rows:
        if not row[COLUMN["Section"]].startswith("World"):
            continue
        base = _base(row[COLUMN["Statistics_detail"]])
        key = (row[COLUMN["Commodity"]], row[COLUMN["Statistics"]], base.lower(), row[COLUMN["Unit"]],
               row[COLUMN["Year"]])
        if key not in groups:
            groups[key] = {"row": row, "base": base, "country_base": None, "world": [], "other": [], "countries": []}
            order.append(key)
        group = groups[key]
        country = row[COLUMN["Country"]]
        if country == WORLD:
            group["world"].append(row)
        elif country == OTHER:
            group["other"].append(row)
        else:
            group["countries"].append(row)
            if group["country_base"] is None:
                group["country_base"] = base
    built, seen = [], set()
    for key in order:
        item = _series(chapter, groups[key], key, problems)
        if item["id"] in seen:
            raise UsgsRefused("two series share the id " + item["id"])
        seen.add(item["id"])
        built.append(item)
    return built, problems


def _world_problem(group, world):
    """Why the series' world total cannot be divided by, or None when it is one positive number."""
    if len(group["world"]) > 1:
        return "USGS prints more than one world total for this series"
    if world is None:
        return "USGS prints no world total for this series"
    if world["number"] is None:
        return "The world total is printed as “" + world["value"] + "”, not as a number"
    if _fraction(world["number"]) <= 0:
        return "The world total is printed as “" + world["value"] + "”, so no share can be computed"
    return None


def _series(chapter, group, key, problems):
    commodity, statistic, _, unit, year = key
    detail = group["country_base"] if group["country_base"] is not None else group["base"]
    sid = "/".join([chapter_id(chapter), chapter_id(statistic), chapter_id(group["base"]), chapter_id(unit), year])
    world = _cell(group["world"][0]) if group["world"] else None
    if world is not None:  # USGS marks a rounded world total in its detail (": rounded" or ", rounded").
        world["rounded"] = ROUNDED.search(group["world"][0][COLUMN["Statistics_detail"]].strip()) is not None
    other = _cell(group["other"][0]) if group["other"] else None
    problem = _world_problem(group, world)
    if len(group["world"]) > 1:
        no_shares = problem
    elif not group["countries"] and not group["other"]:
        no_shares = "USGS prints no country for this series"
    else:
        no_shares = problem
    total = _fraction(world["number"]) if no_shares is None else None

    def share(cell):
        if no_shares is not None:
            return {"shown": None, "reason": no_shares}
        if cell["number"] is None:
            return {"shown": None, "reason": _printed(cell["value"])}
        return {"shown": _percent(_fraction(cell["number"]), total), "reason": None}

    countries = []
    for row in group["countries"]:
        cell = _cell(row)
        cell["country"] = row[COLUMN["Country"]]
        cell["share"] = share(cell)
        countries.append(cell)
    if other is not None:
        other["share"] = share(other)
    problems[sid] = problem
    return {"id": sid, "section": group["row"][COLUMN["Section"]], "commodity": commodity, "statistic": statistic,
            "detail": detail, "unit": unit, "year": year, "world": world, "other": other, "countries": countries,
            "leader": _top(countries, 1, "No countries are named", no_shares, total),
            "top3": _top(countries, 3, "Fewer than three countries are named", no_shares, total),
            "no_shares": no_shares, "unit_issue": UNIT_ISSUES.get(sid)}


def _size(cell):
    """A named country's size for the order: its number, zero when it is printed exactly as a dash, or None when it is
    printed any other way (W, NA, XX, a range, a bound or a word), so its size is unknown."""
    if cell["number"] is not None:
        return _fraction(cell["number"])
    return Fraction(0) if cell["value"].strip() == DASH else None


def _top(countries, count, too_few, no_shares, total):
    """The largest `count` named countries and their combined share, or why the order is withheld. A dash counts as
    zero: it never outranks a positive value, and ties follow the name."""
    if no_shares is not None:
        return {"countries": [], "shown": None, "reason": no_shares}
    sizes = []
    for cell in countries:
        size = _size(cell)
        if size is None:
            reason = cell["country"] + " is printed as “" + cell["value"] + "”, so the order is unknown"
            return {"countries": [], "shown": None, "reason": reason}
        sizes.append((size, cell["country"]))
    if len(countries) < count:
        return {"countries": [], "shown": None, "reason": too_few}
    ranked = sorted(sizes, key=lambda item: (-item[0], item[1]))[:count]
    combined = sum((size for size, _ in ranked), Fraction(0))
    return {"countries": [name for _, name in ranked], "shown": _percent(combined, total), "reason": None}


def _qualifier(base, word):
    text = re.sub(re.escape(word), "", base, flags=re.IGNORECASE).replace(",", "").replace(":", "")
    return " ".join(text.split()).lower()


def _years_of_reserves(series, problems):
    entries = []
    for reserves in series:
        if reserves["statistic"] != "Reserves" or reserves["year"] != "2025":
            continue
        for production in series:
            if (production["statistic"] == "Production" and production["year"] == "2025"
                    and production["commodity"] == reserves["commodity"] and production["unit"] == reserves["unit"]
                    and "mine production" in production["detail"].lower()
                    and _qualifier(production["detail"], "mine production") == _qualifier(reserves["detail"], "reserves")):
                entries.append(_years_entry(reserves, production, problems))
                break
    return entries


def _years_entry(reserves, production, problems):
    """Reserves over production (world totals), or why not: each series' world problem, then its unit issue."""
    shown, reason = None, None
    for name, item in (("Reserves", reserves), ("Production", production)):
        why = problems[item["id"]] or item["unit_issue"]
        if why is not None:
            reason = name + ": " + why
            break
    if reason is None:
        years = _fraction(reserves["world"]["number"]) / _fraction(production["world"]["number"])
        shown = YEARS_UNDER_ONE if years < 1 else _show(years, 0)
    return {"reserves": reserves["id"], "production": production["id"], "shown": shown, "reason": reason,
            "label": YEARS_LABEL}


def _imports(rows):
    groups = {}
    for row in rows:
        if row[COLUMN["Section"]] != "Import Sources":
            continue
        detail = row[COLUMN["Statistics_detail"]]
        group = groups.setdefault(detail, {"detail": detail, "years": row[COLUMN["Year"]], "rows": []})
        value = row[COLUMN["Value"]]
        group["rows"].append({"country": row[COLUMN["Country"]], "value": value, "number": number(value)})
    return list(groups.values())


def _reliance(rows):
    """Each net import reliance row as printed, with its commodity: a chapter can print one row per commodity under the
    same detail (bauxite and alumina; titanium sponge and pigment), which only the Commodity column tells apart."""
    return [{"commodity": row[COLUMN["Commodity"]], "detail": row[COLUMN["Statistics_detail"]],
             "year": row[COLUMN["Year"]], "value": row[COLUMN["Value"]]}
            for row in rows if row[COLUMN["Statistics"]] == "Net import reliance"]


def _chapter(name, rows):
    marks = {row[COLUMN["Is critical mineral 2025"]] for row in rows}
    notes = []
    for row in rows:
        text = row[COLUMN["Other notes"]]
        if text and text not in notes:
            notes.append(text)
    series, problems = _series_of(name, rows)
    return {"id": chapter_id(name), "chapter": name, "name": display_name(name), "present": bool(rows),
            "critical": marks.pop() if len(marks) == 1 and marks <= {"Yes", "No"} else None,
            "world_table": any(row[COLUMN["Section"]].startswith("World") for row in rows), "data_notes": notes,
            "series": series, "years_of_reserves": _years_of_reserves(series, problems), "imports": _imports(rows),
            "reliance": _reliance(rows)}


def read(rows):
    """One chapter dict per CHAPTER_NAMES entry, in that order, from the rows of the data-release CSV."""
    if not rows or list(rows[0]) != HEADER:
        raise UsgsRefused("the first row is not the expected header")
    for row in rows[1:]:
        if len(row) != len(HEADER):
            raise UsgsRefused("a row has " + str(len(row)) + " columns, not " + str(len(HEADER)))
    return [_chapter(name, [row for row in rows[1:] if row[0] == name]) for name in CHAPTER_NAMES]

"""Concentration and supply-chain indicators for the metals page (metals-risk-0.1).

It reads no file: it takes the chapters of metals_usgs.read and the same raw rows. Every figure is arithmetic on printed
USGS numbers with exact fractions and half-even rounding; nothing is interpreted or guessed. A named country printed
exactly as a dash counts as zero; any other non-number withholds the indicators of that series with the reason. The
Herfindahl-Hirschman index of a series with an unnamed remainder is a range: the low end treats the remainder as
spread so thin it adds nothing, the high end as one holder of all of it.
"""
from fractions import Fraction
import re

from . import metals_usgs
from .metals_usgs import COLUMN, DASH, OTHER, _fraction, _show

ENGINE = "metals-risk-0.1"
STAGES = ("mining", "refining")
EXPORT = re.compile(r"\bexport", re.IGNORECASE)  # "Mine production: exports" counts a trade flow, not a stage.
MINING = re.compile(r"\bmine\b", re.IGNORECASE)
REFINING = re.compile(r"refin|smelt", re.IGNORECASE)
INDICATOR_STATISTICS = ("Production", "Reserves")


def stage_of(detail):
    """The stage a 2025 production series' printed detail names: other for an export series, else mining, refining or
    other."""
    if EXPORT.search(detail):
        return "other"
    if MINING.search(detail):
        return "mining"
    return "refining" if REFINING.search(detail) else "other"


def _size(printed):
    """A printed figure as an exact number, zero for exactly a dash, None when it is any other non-number."""
    plain = metals_usgs.number(printed)
    if plain is not None:
        return _fraction(plain)
    return Fraction(0) if printed.strip() == DASH else None


def _bounds(sizes, world):
    """The indicators of named sizes against a world total, all exact."""
    named_sum = sum(sizes, Fraction(0))
    low = sum(((size / world) ** 2 for size in sizes), Fraction(0)) * 10000
    high = low + max(Fraction(0), 1 - named_sum / world) ** 2 * 10000
    return {"named_share": _show(named_sum / world * 100, 1), "over_total": named_sum > world,
            "hhi_low": _show(low, 0), "hhi_high": _show(high, 0), "named": sum(1 for size in sizes if size > 0),
            "reason": None}


def _withheld(reason):
    return {"named_share": None, "over_total": None, "hhi_low": None, "hhi_high": None, "named": None,
            "reason": reason}


def _indicators(item):
    if item["no_shares"] is None:
        sizes = [_size(cell["value"]) for cell in item["countries"]]
        if None not in sizes:
            return _bounds(sizes, _fraction(item["world"]["number"]))
    return _withheld(item["no_shares"] or item["top3"]["reason"])


def _exact(shown):
    return Fraction(shown)


def _alternatives(chapter, by_id):
    for pair in chapter["years_of_reserves"]:
        reserves, production = by_id[pair["reserves"]], by_id[pair["production"]]
        if reserves["no_shares"] is not None or production["no_shares"] is not None:
            continue
        made = {cell["country"]: cell["share"]["shown"] for cell in production["countries"]}
        better, only = [], []
        for cell in reserves["countries"]:
            shown = cell["share"]["shown"]
            if shown is None:
                continue
            if cell["country"] not in made:
                only.append({"country": cell["country"], "reserves": shown})
            elif made[cell["country"]] is not None and _exact(shown) > _exact(made[cell["country"]]):
                better.append({"country": cell["country"], "reserves": shown, "production": made[cell["country"]]})
        order = lambda entry: (-_exact(entry["reserves"]), entry["country"])  # noqa: E731
        return sorted(better, key=order), sorted(only, key=order)
    return None, None


def _stages(chapter):
    stages = [{"series": item["id"], "detail": item["detail"], "stage": stage_of(item["detail"]),
               "leader": item["leader"], "top3": item["top3"]}
              for item in chapter["series"] if item["statistic"] == "Production" and item["year"] == "2025"]
    missing = [name for name in STAGES if not any(stage["stage"] == name for stage in stages)]

    def first_leader(name):
        for stage in stages:
            if stage["stage"] == name and stage["leader"]["shown"] is not None:
                return stage["leader"]["countries"][0]
        return None

    mining, refining = first_leader("mining"), first_leader("refining")
    differ = None if mining is None or refining is None else mining != refining
    top, top_share = None, None
    for stage in stages:
        shown = stage["leader"]["shown"]
        if shown is not None and (top_share is None or _exact(shown) > top_share):
            top, top_share = stage["series"], _exact(shown)
    return stages, missing, differ, top


def _import_group(group):
    named = [row for row in group["rows"] if row["country"] != OTHER]
    entry = {"detail": group["detail"], "years": group["years"], "leader": None, "top3": None, "hhi_low": None,
             "hhi_high": None, "named_share": None, "reason": None}
    sizes = [_size(row["value"]) for row in named]
    if None in sizes:
        entry["reason"] = "A named source is printed as “" + named[sizes.index(None)]["value"] + "”"
        return entry
    bounds = _bounds(sizes, Fraction(100))
    for key in ("named_share", "hhi_low", "hhi_high"):
        entry[key] = bounds[key]
    ranked = sorted(zip(sizes, named), key=lambda item: (-item[0], item[1]["country"]))
    if ranked:
        entry["leader"] = {"country": ranked[0][1]["country"], "value": ranked[0][1]["value"]}
    if len(ranked) >= 3:
        entry["top3"] = _show(sum((size for size, _ in ranked[:3]), Fraction(0)), 1)
    return entry


def _us(chapter, rows):
    reliance = next(({"commodity": row["commodity"], "detail": row["detail"], "value": row["value"]}
                     for row in chapter["reliance"] if row["year"] == "2025"), None)
    secondary = []
    for row in rows:
        detail = row[COLUMN["Statistics_detail"]]
        if (row[0] == chapter["chapter"] and row[COLUMN["Section"]].startswith("Salient Statistics")
                and row[COLUMN["Statistics"]] == "Production" and row[COLUMN["Year"]] == "2025"
                and ("econdary" in detail or "scrap" in detail.lower())):
            secondary.append({"detail": detail, "unit": row[COLUMN["Unit"]], "value": row[COLUMN["Value"]]})
    return {"reliance": reliance, "imports": [_import_group(group) for group in chapter["imports"]],
            "secondary": secondary}


def _entry(chapter, rows):
    by_id = {item["id"]: item for item in chapter["series"]}
    series = {item["id"]: _indicators(item) for item in chapter["series"]
              if item["year"] == "2025" and item["statistic"] in INDICATOR_STATISTICS}
    stages, missing, differ, top = _stages(chapter)
    alternatives, reserves_only = _alternatives(chapter, by_id)
    return {"id": chapter["id"], "series": series, "stages": stages, "missing_stages": missing,
            "leaders_differ": differ, "most_concentrated": top, "alternatives": alternatives,
            "reserves_only": reserves_only, "us": _us(chapter, rows)}


def read(chapters, rows):
    """One entry per chapter, in chapter order. `rows` are the raw CSV rows (header first) the chapters came from."""
    return [_entry(chapter, rows[1:]) for chapter in chapters]

"""Cards and full tables for the industry findings (g17-text-0.1): fixed templates filled from verified comparisons.

Divergence cards use, for each comparison and reference month, the latest selected release that prints that month; a
card needs opposing printed directions. They are ordered by reference month (latest first), then by the absolute gap in
percentage points, then by row path, and at most six are shown with the totals beside them. Revision cards are strict
reversals between consecutive selected releases, ordered by the absolute revision, then month, then path; changes to or
from a printed 0.0 are listed apart, never as reversals. Observations, what the comparison adds, the interpretation and
the limitations are separate fields.
"""
from calendar import month_name
from decimal import Decimal

from . import g17_rules as rules

TEXT_VERSION = "g17-text-0.1"
SHOWN = 6
DIVERGENCE_ORDER = ("Latest selected release printing each month; opposing printed directions only; ordered by "
                    "reference month (latest first), then the absolute gap in percentage points, then row path.")
REVISION_ORDER = ("Strict reversals between consecutive selected releases; ordered by the absolute revision in "
                  "percentage points, then reference month (latest first), then row path.")
LIMITATIONS = (
    "Published rates are rounded to 0.1 percent: differences under 0.05 point cannot be seen, and a printed 0.0 has no "
    "resolvable direction.",
    "Rates are seasonally adjusted monthly percent changes; nothing here uses index levels, weights or contributions to "
    "the total, so a row's size within its parent is not assessed.",
    "Archived release pages are compared as the versions published on their release dates; matching archived pages do "
    "not prove the historical bytes are unchanged.",
    "Revisions are changes in published estimates for the same month, not activity between release dates. The earliest "
    "retained estimate is the first publication only where it is marked preliminary [p].",
    "Descriptions of published estimates: no statistical significance, independent corroboration, causes, trading "
    "implications or forecasts.",
)


def month_label(key: str) -> str:
    return f"{month_name[int(key[5:])]} {key[:4]}"


def rate_text(text: str | None) -> str:
    if text is None:
        return "not printed"
    value = Decimal(text)
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{format(abs(value), 'f')}%"


def pp_text(text: str | None) -> str:
    if text is None:
        return "—"
    value = Decimal(text)
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{format(abs(value), 'f')} pp"


def _label(path: str) -> str:
    return path.split(" / ")[-1]


def _named(path: str, naics: str | None) -> str:
    """A row's label with its NAICS code where the table prints one, so equal labels stay distinguishable."""
    if not naics:
        return _label(path)
    return f"{_label(path)} (codes {naics})" if "NAICS" in _label(path) else f"{_label(path)} (NAICS {naics})"


def _lower(label: str) -> str:
    return label if label.isupper() or label.startswith("NAICS") else label[0].lower() + label[1:]


def _verb(text: str) -> str:
    return "rose" if Decimal(text) > 0 else "fell"


def _observed(extract: dict, path: str, month: dict, rate: str | None) -> dict:
    row = next(item for item in extract["rows"] if item["path"] == path)
    table = next(source for source in extract["sources"] if source["role"] == "Table 1")
    return {"label": row["label"], "path": path, "naics": row["naics"], "rate": rate, "rate_text": rate_text(rate),
            "month": month["key"], "column": month["column"], "marker": month["marker"], "table": "Table 1",
            "url": table["url"], "sha256": table["sha256"], "release": extract["release"],
            "release_date_as_stated": extract["release_date_as_stated"]}


def _vintages(extracts: list[dict], results: dict, item: dict) -> list[dict]:
    out = []
    for extract in extracts:
        for other in results[extract["release"]]["comparisons"]:
            if (other["row"], other["parent"], other["month"]) == (item["row"], item["parent"], item["month"]):
                out.append({"release": extract["release"], "release_date_as_stated": extract["release_date_as_stated"],
                            "marker": other["marker"], "row_rate": other["row_rate"],
                            "parent_rate": other["parent_rate"], "relation": other["relation"]})
    return out


def divergence(extracts: list[dict], results: dict) -> dict:
    """Divergence cards from the latest estimate of every comparison and month, with totals and no-direction notes."""
    latest = {}
    for extract in extracts:  # Ordered by release date: a later release replaces an earlier estimate of the month.
        for item in results[extract["release"]]["comparisons"]:
            latest[(item["row"], item["parent"], item["month"])] = (extract, item)
    counts = {name: 0 for name in rules.DEFINITIONS["release_relations"]}
    cards, quiet = [], {}
    for extract, item in latest.values():
        counts[item["relation"]] += 1
        if item["relation"] == "no_direction" and item["printed_zero_or_missing"] in ("parent", "both"):
            key = (item["parent"], item["month"], extract["release"])
            quiet.setdefault(key, {"parent": item["parent"], "parent_label": _label(item["parent"]),
                                   "month": item["month"], "month_label": month_label(item["month"]),
                                   "release": extract["release"],
                                   "release_date_as_stated": extract["release_date_as_stated"],
                                   "parent_rate": item["parent_rate"], "comparisons": 0})["comparisons"] += 1
        if item["relation"] != "opposing":
            continue
        month = next(m for m in extract["months"] if m["key"] == item["month"])
        row_label, parent_label = _label(item["row"]), _label(item["parent"])
        whole = "Total industrial production" if item["parent"] == rules.TOTAL else parent_label
        vintages = _vintages(extracts, results, item)
        notes = []
        if month["marker"] == "p":
            notes.append(f"{month_label(item['month'])} is the preliminary estimate in this release; later releases "
                         "may revise it.")
        if Decimal(item["row_rate"]).copy_abs() == Decimal("0.1") or Decimal(item["parent_rate"]).copy_abs() == \
                Decimal("0.1"):
            notes.append("A printed ±0.1 is one rounding step from 0.0.")
        if any(v["relation"] != "opposing" for v in vintages):
            notes.append("Not opposing in every selected release that prints this month (see the estimates).")
        cards.append({
            "type": "divergence", "id": f"{extract['release']}|{item['month']}|{item['row']}",
            "kind": item["kind"], "title": f"{_named(item['row'], item['row_naics'])} {_verb(item['row_rate'])} while "
                                           f"{_lower(whole)} {_verb(item['parent_rate'])}",
            "month": item["month"], "month_label": month_label(item["month"]), "gap_pp": item["gap_pp"],
            "observed": [_observed(extract, item["row"], month, item["row_rate"]),
                         _observed(extract, item["parent"], month, item["parent_rate"])],
            "adds": (f"{whole} at {rate_text(item['parent_rate'])} for {month_label(item['month'])} does not show that "
                     f"{_lower(row_label)} ({rate_text(item['row_rate'])}) moved the other way in the same month."),
            "interpretation": ("In this published estimate the direction of the " +
                               ("total" if item["parent"] == rules.TOTAL else "parent") + " did not hold for this " +
                               ("industry group" if item["kind"] == "group_vs_total" else "subsector") +
                               ". It describes printed rates only; it does not say why."),
            "limitations": notes, "estimates": vintages})
    cards.sort(key=lambda card: (-int(card["month"].replace("-", "")), -abs(Decimal(card["gap_pp"])),
                                 card["observed"][0]["path"]))
    return {"order": DIVERGENCE_ORDER, "comparisons": len(latest), "counts": counts, "total": len(cards),
            "shown": cards[:SHOWN], "no_direction_parents": sorted(quiet.values(), key=lambda q: (q["month"],
                                                                                                  q["parent"]))}


def chains(extracts: list[dict]) -> dict:
    """(row path, month) -> every selected release's printed estimate, oldest release first."""
    out = {}
    for extract in extracts:
        table = next(source for source in extract["sources"] if source["role"] == "Table 1")
        months = {m["key"]: m for m in extract["months"]}
        for row in rules.revision_rows(extract):
            for key, rate in row["rates"].items():
                out.setdefault((row["path"], key), []).append({
                    "release": extract["release"], "release_date_as_stated": extract["release_date_as_stated"],
                    "rate": rate, "rate_text": rate_text(rate), "marker": months[key]["marker"],
                    "column": months[key]["column"], "url": table["url"], "naics": row["naics"]})
    return out


def revisions(extracts: list[dict], pairs: list[dict]) -> dict:
    by_release = {extract["release"]: extract for extract in extracts}
    estimates = chains(extracts)
    counts = {name: 0 for name in rules.DEFINITIONS["revision_kinds"]}
    cards, zero = [], []
    for pair in pairs:
        earlier, later = by_release[pair["earlier"]], by_release[pair["later"]]
        for item in pair["comparisons"]:
            counts[item["kind"]] += 1
            label, month = _label(item["row"]), month_label(item["month"])
            if item["kind"] in ("to_printed_zero", "from_printed_zero"):
                zero.append({"row": item["row"], "label": label, "month": item["month"], "month_label": month,
                             "kind": item["kind"], "earlier": {**item["earlier"], "release": earlier["release"],
                                                               "release_date_as_stated":
                                                                   earlier["release_date_as_stated"]},
                             "later": {**item["later"], "release": later["release"],
                                       "release_date_as_stated": later["release_date_as_stated"]},
                             "revision_pp": item["revision_pp"]})
            if item["kind"] != "reversal":
                continue
            a, b = item["earlier"], item["later"]
            notes = []
            first = estimates[(item["row"], item["month"])][0]
            if first["marker"] != "p":
                notes.append(f"The earliest selected estimate of {month} is already revised [r]; its first "
                             "publication is not retained here.")
            if Decimal(a["rate"]).copy_abs() == Decimal("0.1") or Decimal(b["rate"]).copy_abs() == Decimal("0.1"):
                notes.append("A printed ±0.1 is one rounding step from 0.0.")
            cards.append({
                "type": "revision", "id": f"{earlier['release']}>{later['release']}|{item['month']}|{item['row']}",
                "title": f"{_named(item['row'], item['naics'])}, {month}: reported "
                         f"{'up' if Decimal(a['rate']) > 0 else 'down'}, then {'up' if Decimal(b['rate']) > 0 else 'down'}",
                "row": item["row"], "naics": item["naics"], "month": item["month"], "month_label": month,
                "from": {"release": earlier["release"], "release_date_as_stated": earlier["release_date_as_stated"],
                         **a, "rate_text": rate_text(a["rate"])},
                "to": {"release": later["release"], "release_date_as_stated": later["release_date_as_stated"],
                       **b, "rate_text": rate_text(b["rate"])},
                "revision_pp": item["revision_pp"], "chain": estimates[(item["row"], item["month"])],
                "adds": (f"Reading only the {earlier['release_date_as_stated']} release, {_lower(label)} "
                         f"{_verb(a['rate'])} {rate_text(a['rate']).lstrip('+−')} in {month}; the "
                         f"{later['release_date_as_stated']} release prints {rate_text(b['rate'])} for the same month."),
                "interpretation": ("The published estimate for the same month changed direction between releases. "
                                   "This is a revision to a published estimate, not activity between release dates."),
                "limitations": notes})
    cards.sort(key=lambda card: (-abs(Decimal(card["revision_pp"])), -int(card["month"].replace("-", "")),
                                 card["row"]))
    zero.sort(key=lambda item: (item["month"], item["row"]))
    return {"order": REVISION_ORDER, "counts": counts, "total": len(cards), "shown": cards[:SHOWN],
            "printed_zero_transitions": zero}


def tables(extracts: list[dict], results: dict, pairs: list[dict]) -> dict:
    """Every comparison of every selected release, and every revision chain, for the full-table page."""
    releases = []
    for extract in extracts:
        releases.append({"release": extract["release"], "release_date_as_stated": extract["release_date_as_stated"],
                         "months": [{"key": m["key"], "label": month_label(m["key"]), "marker": m["marker"],
                                     "column": m["column"]} for m in extract["months"]],
                         "comparisons": results[extract["release"]]["comparisons"],
                         "counts": results[extract["release"]]["counts"]})
    kinds = {(pair["earlier"], pair["later"], item["row"], item["month"]): item["kind"]
             for pair in pairs for item in pair["comparisons"]}
    rows = []
    estimates = chains(extracts)
    paths = list(dict.fromkeys(path for path, _ in estimates))
    months = sorted({month for _, month in estimates})
    for path in paths:
        cells = []
        for month in months:
            chain = estimates.get((path, month), [])
            steps = [kinds.get((a["release"], b["release"], path, month)) for a, b in zip(chain, chain[1:])]
            cells.append({"month": month, "estimates": chain, "steps": steps})
        first = next(chain for (p, _), chain in estimates.items() if p == path)
        rows.append({"path": path, "label": _label(path), "naics": first[0]["naics"], "cells": cells})
    return {"by_release": releases, "months": [{"key": m, "label": month_label(m)} for m in months],
            "revision_rows": rows}

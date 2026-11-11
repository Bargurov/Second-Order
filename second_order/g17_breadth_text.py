"""Manufacturing breadth cards and tables (g17-breadth-text-0.1): fixed templates filled from verified breadth results.

Selection: aggregate-against-breadth cards, one per reference month, from the latest selected release printing that
month (the other releases' verdicts listed beside it); breadth shifts from the consecutive months of the latest selected
release only, so months of different release versions are never stitched together; breadth revisions for the same month
in consecutive releases. Ordered by kind, then reference month (latest first); at most six shown, with totals per kind.
"""
from . import g17_breadth
from .g17_rules import direction
from .g17_text import SHOWN, month_label, rate_text

ORDER = ("Aggregate against breadth: one card per reference month, from the latest selected release printing it. Breadth "
         "shifts: consecutive months of the latest selected release only. Breadth revisions: the same month in "
         "consecutive releases. Ordered by kind, then reference month (latest first).")
ADDS = ("The Manufacturing (NAICS) rate is one number. The counts show how many of its 19 subsectors were printed up, "
        "down or 0.0 in the same month and release, whether that changed from month to month within one release, and "
        "whether later releases changed it for the same month.")
LIMITATIONS = (
    "Unweighted counts of 19 named subsectors: not contributions to the aggregate, not weights and not the whole "
    "economy. Mining, utilities and other (non-NAICS) manufacturing are outside this universe.",
    "Subsectors differ in size and in the size of their changes, so the aggregate and the count can point different "
    "ways; these inputs do not show which subsectors drove the aggregate.",
    "A printed 0.0 has no resolvable direction and counts in neither direction; shares and majorities are shown only "
    "when all 19 are printed.",
)
STATE_TEXT = {"majority_up": "most subsectors up", "majority_down": "most subsectors down",
              "no_majority": "no majority either way", "incomplete": "incomplete (a subsector is not printed)"}
SHIFT_PHRASES = {("majority_up", "no_majority"): "reported increases became less widespread",
                 ("no_majority", "majority_up"): "reported increases became more widespread",
                 ("majority_down", "no_majority"): "reported declines became less widespread",
                 ("no_majority", "majority_down"): "reported declines became more widespread",
                 ("majority_up", "majority_down"): "from mostly reported increases to mostly reported declines",
                 ("majority_down", "majority_up"): "from mostly reported declines to mostly reported increases"}
KIND_ORDER = {"aggregate_vs_breadth": 0, "breadth_shift": 1, "breadth_revision": 2}


def counts_text(counts: dict) -> str:
    parts = [f"{counts['positive']} up", f"{counts['negative']} down", f"{counts['printed_zero']} printed 0.0"]
    if counts["missing"]:
        parts.append(f"{counts['missing']} not printed")
    return ", ".join(parts)


def _month(month: dict) -> dict:
    return {**{key: month[key] for key in ("month", "column", "marker", "expected", "counts", "groups",
                                           "aggregate_rate", "state", "aggregate_vs_breadth")},
            "month_label": month_label(month["month"]), "aggregate_rate_text": rate_text(month["aggregate_rate"]),
            "state_text": STATE_TEXT[month["state"]], "counts_text": counts_text(month["counts"]),
            "shares": {name: g17_breadth.share_text(month["counts"][name])
                       for name in ("positive", "negative", "printed_zero")} if month["shares"] else None,
            "members": {name: [f"{m['label']} ({m['naics']})" for m in month["members"][name]]
                        for name in month["members"]}}


def _source(extract: dict) -> dict:
    table = next(source for source in extract["sources"] if source["role"] == "Table 1")
    return {"release": extract["release"], "release_date_as_stated": extract["release_date_as_stated"],
            "url": table["url"], "sha256": table["sha256"], "table": "Table 1"}


def _against_cards(extracts: list[dict], results: dict) -> list[dict]:
    latest = {}
    for extract in extracts:  # Release-date order: a later release replaces an earlier estimate of the month.
        for month in results[extract["release"]]["months"]:
            latest[month["month"]] = (extract, month)
    cards = []
    for key, (extract, month) in latest.items():
        if not month["aggregate_vs_breadth"]:
            continue
        up = month["aggregate_direction"] > 0
        opposite = month["counts"]["negative" if up else "positive"]
        estimates = [{"release": e["release"], "release_date_as_stated": e["release_date_as_stated"],
                      "marker": m["marker"], "counts_text": counts_text(m["counts"]),
                      "aggregate_rate_text": rate_text(m["aggregate_rate"]), "met": m["aggregate_vs_breadth"]}
                     for e in extracts for m in results[e["release"]]["months"] if m["month"] == key]
        notes = [f"{month_label(key)} is the preliminary estimate in this release; later releases may revise it."] \
            if month["marker"] == "p" else []
        if any(not estimate["met"] for estimate in estimates):
            notes.append("Not met in every selected release that prints this month (see the estimates).")
        cards.append({
            "type": "aggregate_vs_breadth", "id": f"avb|{extract['release']}|{key}", "month": key,
            "title": (f"{month_label(key)}: Manufacturing (NAICS) {'rose' if up else 'fell'} "
                      f"{rate_text(month['aggregate_rate']).lstrip('+−')} while {opposite} of {month['expected']} "
                      f"subsectors were printed {'down' if up else 'up'}"),
            "source": _source(extract), "observed": [_month(month)],
            "adds": (f"The aggregate rate alone points {'up' if up else 'down'}; more than half of the 19 NAICS "
                     f"subsectors were printed {'down' if up else 'up'} in the same estimate."),
            "interpretation": ("Subsectors differ in weight and in the size of their changes, so a minority can carry "
                               "the aggregate; these unweighted counts do not show which subsectors did."),
            "limitations": notes, "estimates": estimates})
    return cards


def _shift_cards(extract: dict, result: dict) -> list[dict]:
    if result["state"] != "computed":
        return []
    months = {m["month"]: m for m in result["months"]}
    cards = []
    for shift in result["shifts"]:
        if not shift["shift"]:
            continue
        before, after = months[shift["from"]], months[shift["to"]]
        cards.append({
            "type": "breadth_shift", "id": f"shift|{extract['release']}|{shift['to']}", "month": shift["to"],
            "title": (f"{month_label(shift['from'])} to {month_label(shift['to'])}: "
                      f"{SHIFT_PHRASES[(before['state'], after['state'])]}"),
            "source": _source(extract), "observed": [_month(before), _month(after)], "change": shift["change"],
            "adds": (f"Both months come from the {extract['release_date_as_stated']} release, so the comparison does not "
                     "mix release versions."),
            "interpretation": ("This counts how many named subsectors were printed up or down in each month; it does not "
                               "measure the size of the changes or their weight in the aggregate."),
            "limitations": []})
    return cards


def _revision_cards(by_release: dict, pairs: list[dict]) -> list[dict]:
    cards = []
    for pair in pairs:
        if pair["state"] != "computed":
            continue
        earlier, later = by_release[pair["earlier"]], by_release[pair["later"]]
        for month in pair["months"]:
            if not month["changed"]:
                continue
            label = month_label(month["month"])
            notes = [] if month["earlier"]["marker"] == "p" else [
                f"The earlier estimate of {label} is already revised [r]; its first publication is not retained here."]
            condition = None
            if month["earlier"]["aggregate_vs_breadth"] != month["later"]["aggregate_vs_breadth"]:
                held, other = (("earlier", earlier), ("later", later)) if month["earlier"]["aggregate_vs_breadth"] \
                    else (("later", later), ("earlier", earlier))
                side = month[held[0]]
                rising = direction(side["aggregate_rate"]) > 0  # Known: the condition needs a printed direction.
                opposite = side["counts"]["negative" if rising else "positive"]
                condition = (f"In the {held[1]['release_date_as_stated']} release the aggregate stood against most "
                             f"subsectors: Manufacturing (NAICS) {rate_text(side['aggregate_rate'])} with {opposite} of "
                             f"19 printed {'down' if rising else 'up'}; in the {other[1]['release_date_as_stated']} "
                             "release it did not.")
            cards.append({
                "type": "breadth_revision", "id": f"rev|{pair['earlier']}|{pair['later']}|{month['month']}",
                "month": month["month"],
                "title": (f"{label} breadth revised: {STATE_TEXT[month['earlier']['state']]} in the "
                          f"{earlier['release_date_as_stated']} release, {STATE_TEXT[month['later']['state']]} in the "
                          f"{later['release_date_as_stated']} release"),
                "earlier": {**_source(earlier), "counts_text": counts_text(month["earlier"]["counts"]),
                            "marker": month["earlier"]["marker"],
                            "aggregate_rate_text": rate_text(month["earlier"]["aggregate_rate"])},
                "later": {**_source(later), "counts_text": counts_text(month["later"]["counts"]),
                          "marker": month["later"]["marker"],
                          "aggregate_rate_text": rate_text(month["later"]["aggregate_rate"])},
                "change": month["change"], "reversals": month["reversals"],
                "printed_zero_transitions": month["printed_zero_transitions"],
                "adds": (f"Reading only the {earlier['release_date_as_stated']} release would describe {label} as "
                         f"{STATE_TEXT[month['earlier']['state']]}; the {later['release_date_as_stated']} release "
                         f"prints {counts_text(month['later']['counts'])}."),
                "interpretation": ("A revision of published estimates for the same month, not activity between the "
                                   "release dates."),
                "condition": condition, "limitations": notes})
    return cards


def summary(extracts: list[dict], results: dict, pairs: list[dict]) -> dict:
    """The latest selected release's breadth, the cards with their totals, and the universe."""
    by_release = {extract["release"]: extract for extract in extracts}
    latest = extracts[-1]
    latest_result = results[latest["release"]]
    cards = (_against_cards(extracts, results) + _shift_cards(latest, latest_result)
             + _revision_cards(by_release, pairs))
    cards.sort(key=lambda card: (KIND_ORDER[card["type"]], -int(card["month"].replace("-", "")), card["id"]))
    for card in cards:
        card["month_label"] = month_label(card["month"])
    totals = {kind: sum(1 for card in cards if card["type"] == kind) for kind in KIND_ORDER}
    switched = sum(1 for pair in pairs if pair["state"] == "computed" for month in pair["months"]
                   if month["counts_unchanged_members_switched"])
    return {"universe": {"expected": g17_breadth.EXPECTED, "durable": len(g17_breadth.UNIVERSE["durable"]),
                         "nondurable": len(g17_breadth.UNIVERSE["nondurable"]), "aggregate": g17_breadth.AGGREGATE,
                         "excluded": g17_breadth.DEFINITIONS["excluded"]},
            "latest": {**_source(latest), "state": latest_result["state"], "detail": latest_result["detail"],
                       "months": [_month(m) for m in latest_result["months"]]},
            "order": ORDER, "adds": ADDS, "limitations": list(LIMITATIONS), "totals": totals, "total": len(cards),
            "shown": cards[:SHOWN], "counts_unchanged_members_switched": switched}


def tables(extracts: list[dict], results: dict, pairs: list[dict]) -> dict:
    by_release = {extract["release"]: extract for extract in extracts}
    releases = [{**_source(extract), "state": results[extract["release"]]["state"],
                 "detail": results[extract["release"]]["detail"],
                 "months": [_month(m) for m in results[extract["release"]]["months"]],
                 "shifts": [{**shift, "from_label": month_label(shift["from"]), "to_label": month_label(shift["to"])}
                            for shift in results[extract["release"]]["shifts"]]} for extract in extracts]
    revisions = [{"earlier": _source(by_release[pair["earlier"]]), "later": _source(by_release[pair["later"]]),
                  "state": pair["state"], "detail": pair["detail"],
                  "months": [{**month, "month_label": month_label(month["month"]),
                              "earlier_text": counts_text(month["earlier"]["counts"]),
                              "later_text": counts_text(month["later"]["counts"])} for month in pair["months"]]}
                 for pair in pairs]
    return {"releases": releases, "revisions": revisions}

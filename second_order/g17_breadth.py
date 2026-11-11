"""Manufacturing breadth on verified G.17 extracts (g17-breadth-0.1). No I/O.

Universe. The 19 NAICS manufacturing subsectors of Table 1: the 11 coded rows directly under Durable manufacturing and the
8 under Nondurable manufacturing (both under Manufacturing (NAICS), 31-33), each identified by its full row path and
NAICS code. A release's breadth is computed only when its table has exactly these rows under those parents; otherwise it
is unavailable, with the difference stated. Parent rows are never counted with their children, and mining, utilities,
other (non-NAICS) manufacturing, market groups and Table 2 aggregates are outside the universe. The aggregate it is set
against is Manufacturing (NAICS), not broad Manufacturing or Total IP.

Counts. For each release and reference month: subsectors whose printed seasonally adjusted monthly rate is above 0.0
(positive), below (negative), printed 0.0 or -0.0 (no resolvable direction; not exact zero), or blank (missing), with the
expected size 19, by durable/nondurable group, and the members of each class. Breadth is unweighted: a count of named
subsectors, not a contribution to the aggregate, a weight concentration or a measure of the whole economy.

Completeness. Shares (count / 19, the printed zeros included in the denominator) and majority states exist only when all
19 observations are present. A month with a missing observation keeps its partial counts and coverage, its state is
"incomplete", and it enters no finding.

State of a complete month: "majority_up" when more than half of the 19 are positive (10 or more), "majority_down" when
more than half are negative, otherwise "no_majority".

Findings (fixed before any acceptance run; zero findings is a valid outcome):
- aggregate_vs_breadth (one release, one month): complete; the aggregate's printed direction is known (not 0.0); more
  than half of the 19 have the opposite printed direction.
- breadth_shift (one release, consecutive reference months): both complete and their states differ.
- breadth_revision (consecutive releases, the same reference month): both complete and the state or the
  aggregate_vs_breadth condition differs. Every compared month also records count changes and which subsectors switched:
  strict reversals (positive to negative or back) apart from transitions to or from a printed 0.0, so a change of members
  under unchanged counts stays visible.
"""
from decimal import ROUND_HALF_UP, Decimal

from .g17_rules import NAICS_MANUFACTURING, PARENTS, direction
from .store import digest

BREADTH_VERSION = "g17-breadth-0.1"
DURABLE, NONDURABLE = PARENTS
AGGREGATE = NAICS_MANUFACTURING[0]
UNIVERSE = {
    "durable": [("Wood products", "321"), ("Nonmetallic mineral products", "327"), ("Primary metals", "331"),
                ("Fabricated metal products", "332"), ("Machinery", "333"), ("Computer and electronic products", "334"),
                ("Electrical equip., appliances, and components", "335"), ("Motor vehicles and parts", "3361-3"),
                ("Aerospace and miscellaneous transportation equipment", "3364-9"),
                ("Furniture and related products", "337"), ("Miscellaneous", "339")],
    "nondurable": [("Food, beverage, and tobacco products", "311,2"), ("Textile and product mills", "313,4"),
                   ("Apparel and leather", "315,6"), ("Paper", "322"), ("Printing and support", "323"),
                   ("Petroleum and coal products", "324"), ("Chemicals", "325"), ("Plastics and rubber products", "326")],
}
GROUP_PARENT = {"durable": DURABLE, "nondurable": NONDURABLE}
EXPECTED = sum(len(rows) for rows in UNIVERSE.values())
CLASSES = ("positive", "negative", "printed_zero", "missing")
DEFINITIONS = {
    "version": BREADTH_VERSION,
    "universe": {group: [{"path": f"{GROUP_PARENT[group]} / {label}", "naics": code} for label, code in rows]
                 for group, rows in UNIVERSE.items()},
    "expected": EXPECTED,
    "aggregate": {"path": AGGREGATE, "naics": NAICS_MANUFACTURING[1]},
    "excluded": "Mining, utilities, other (non-NAICS) manufacturing, parent rows, market groups and Table 2 aggregates.",
    "classes": "positive: printed above 0.0; negative: below 0.0; printed_zero: 0.0 or -0.0 (no direction); missing.",
    "shares": "Only when all 19 are present: count / 19, printed zeros included in the denominator.",
    "states": "majority_up: positive x 2 > 19; majority_down: negative x 2 > 19; no_majority; incomplete if missing.",
    "findings": {
        "aggregate_vs_breadth": "One release and month, complete, aggregate printed up (down), more than half of the "
                                "19 printed down (up).",
        "breadth_shift": "One release, consecutive complete months, different states.",
        "breadth_revision": "Consecutive releases, the same complete month, a different state or a different "
                            "aggregate_vs_breadth condition.",
    },
    "weights": "Unweighted counts of named subsectors; not contributions, weights or the whole economy.",
}
DEFINITIONS_SHA256 = digest(DEFINITIONS)


def _class(text: str | None) -> str:
    sign = direction(text)
    return "missing" if sign is None else "printed_zero" if sign == 0 else "positive" if sign > 0 else "negative"


def universe_problem(extract: dict) -> str | None:
    """Why this extract's subsectors are not the defined 19 under their parents, or None when they are."""
    rows = {row["path"]: row for row in extract["rows"]}
    problems = []
    for group, parent in GROUP_PARENT.items():
        if parent not in rows:
            problems.append(f"no {parent!r} row")
            continue
        depth = rows[parent]["depth"] + 1
        found = {(row["path"], row["naics"]) for row in extract["rows"]
                 if row["path"].startswith(parent + " / ") and row["depth"] == depth}
        wanted = {(f"{parent} / {label}", code) for label, code in UNIVERSE[group]}
        if found != wanted:
            missing = sorted(path.split(" / ")[-1] for path, _ in wanted - found)
            extra = sorted(path.split(" / ")[-1] for path, _ in found - wanted)
            problems.append(f"{group}: expected {len(wanted)} subsectors, found {len(found)}"
                            + (f"; missing or different: {', '.join(missing)}" if missing else "")
                            + (f"; not in the universe: {', '.join(extra)}" if extra else ""))
    if AGGREGATE not in rows or rows[AGGREGATE]["naics"] != NAICS_MANUFACTURING[1]:
        problems.append(f"no {AGGREGATE!r} row coded {NAICS_MANUFACTURING[1]}")
    return "; ".join(problems) or None


def _state(counts: dict) -> str:
    if counts["missing"]:
        return "incomplete"
    if counts["positive"] * 2 > EXPECTED:
        return "majority_up"
    if counts["negative"] * 2 > EXPECTED:
        return "majority_down"
    return "no_majority"


def _against(month: dict) -> bool:
    """aggregate_vs_breadth: a complete month whose aggregate direction is opposed by more than half of the 19."""
    if month["state"] == "incomplete" or month["aggregate_direction"] in (None, 0):
        return False
    opposite = month["counts"]["negative" if month["aggregate_direction"] > 0 else "positive"]
    return opposite * 2 > EXPECTED


def release_breadth(extract: dict) -> dict:
    """Every reference month of one release, as published in that release."""
    problem = universe_problem(extract)
    if problem:
        return {"release": extract["release"], "state": "unavailable", "detail": problem, "months": [], "shifts": [],
                "findings": []}
    rows = {row["path"]: row for row in extract["rows"]}
    months = []
    for month in extract["months"]:
        key = month["key"]
        members = {name: [] for name in CLASSES}
        groups = {}
        for group, entries in UNIVERSE.items():
            counts = {name: 0 for name in CLASSES}
            for label, code in entries:
                rate = rows[f"{GROUP_PARENT[group]} / {label}"]["rates"][key]
                name = _class(rate)
                counts[name] += 1
                members[name].append({"label": label, "naics": code, "group": group, "rate": rate})
            groups[group] = {**counts, "expected": len(entries)}
        counts = {name: sum(groups[group][name] for group in groups) for name in CLASSES}
        aggregate = rows[AGGREGATE]["rates"][key]
        item = {"month": key, "column": month["column"], "marker": month["marker"], "expected": EXPECTED,
                "counts": counts, "groups": groups, "members": members, "aggregate_rate": aggregate,
                "aggregate_direction": direction(aggregate),
                "shares": {name: f"{counts[name]}/{EXPECTED}" for name in CLASSES if name != "missing"}
                if not counts["missing"] else None}
        item["state"] = _state(counts)
        item["aggregate_vs_breadth"] = _against(item)
        months.append(item)
    shifts = []
    for before, after in zip(months, months[1:]):
        compared = before["state"] != "incomplete" and after["state"] != "incomplete"
        shifts.append({"from": before["month"], "to": after["month"],
                       "change": {name: after["counts"][name] - before["counts"][name] for name in CLASSES},
                       "states": [before["state"], after["state"]], "compared": compared,
                       "shift": compared and before["state"] != after["state"]})
    findings = ([{"type": "aggregate_vs_breadth", "month": m["month"]} for m in months if m["aggregate_vs_breadth"]] +
                [{"type": "breadth_shift", "from": s["from"], "to": s["to"]} for s in shifts if s["shift"]])
    return {"release": extract["release"], "state": "computed", "detail": None, "months": months, "shifts": shifts,
            "findings": findings}


def revision_breadth(earlier: dict, later: dict) -> dict:
    """The same reference month in two consecutive releases, earlier first."""
    if earlier["release_date"] >= later["release_date"]:
        raise ValueError("Breadth revisions need the earlier release first")
    a, b = release_breadth(earlier), release_breadth(later)
    if a["state"] != "computed" or b["state"] != "computed":
        return {"earlier": earlier["release"], "later": later["release"], "state": "unavailable",
                "detail": a["detail"] or b["detail"], "months": [], "findings": []}
    after = {m["month"]: m for m in b["months"]}
    months = []
    for first in a["months"]:
        second = after.get(first["month"])
        if second is None:
            continue
        before_members = {m["naics"]: (m, name) for name in CLASSES for m in first["members"][name]}
        after_members = {m["naics"]: (m, name) for name in CLASSES for m in second["members"][name]}
        reversals, zero, coverage = [], [], []
        for code, (member, old) in before_members.items():
            new = after_members[code][1]
            if old == new:
                continue
            entry = {"label": member["label"], "naics": code, "from": old, "to": new,
                     "earlier_rate": member["rate"], "later_rate": after_members[code][0]["rate"]}
            if {old, new} == {"positive", "negative"}:
                reversals.append(entry)
            elif "missing" in (old, new):
                coverage.append(entry)
            else:
                zero.append(entry)
        compared = first["state"] != "incomplete" and second["state"] != "incomplete"
        changed = compared and (first["state"] != second["state"]
                                or first["aggregate_vs_breadth"] != second["aggregate_vs_breadth"])
        months.append({"month": first["month"],
                       "earlier": {key: first[key] for key in ("counts", "state", "marker", "aggregate_rate",
                                                               "aggregate_vs_breadth")},
                       "later": {key: second[key] for key in ("counts", "state", "marker", "aggregate_rate",
                                                              "aggregate_vs_breadth")},
                       "change": {name: second["counts"][name] - first["counts"][name] for name in CLASSES},
                       "reversals": reversals, "printed_zero_transitions": zero, "coverage_changes": coverage,
                       "counts_unchanged_members_switched": compared and first["counts"] == second["counts"]
                       and bool(reversals or zero),
                       "compared": compared, "changed": changed})
    return {"earlier": earlier["release"], "later": later["release"], "state": "computed", "detail": None,
            "months": months, "findings": [{"type": "breadth_revision", "month": m["month"]}
                                           for m in months if m["changed"]]}


def share_text(count: int) -> str:
    """A count of the 19 as a whole percentage, for display only (the record keeps the exact fraction)."""
    return f"{(Decimal(count) * 100 / EXPECTED).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}%"

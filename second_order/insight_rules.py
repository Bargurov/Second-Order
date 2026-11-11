"""Measurements and exploratory descriptive rules of the Treasury findings pilot (insight-rules-0.1). No I/O.

Grid. The measurement grid is the union of the six yield series' observation grids (insight_evidence): SIFMA sessions,
plus any date a series lists on a calendar holiday, which stays in the grid as missing. A measure's value on a grid date
is its series' value, or a fixed combination of series values on that same date (breakeven = nominal minus
inflation-indexed yield at the same maturity; 2s10s slope = 10-year minus 2-year), and is missing when any component is.

Windows (DEFINITIONS["windows"]), for an event date d0 (a New York calendar date): B1 is the last grid date before d0,
B6 the sixth; A1 and A5 are the first and fifth grid dates after d0. W1 runs from B1 to A1 and W5 from B1 to A5: when
d0 is itself a grid date they include the d0 interval, so they contain any movement on the event date and on the
surrounding sessions; they never isolate a response to the announcement. PRE runs from B6 to B1. A window's span is
its actual number of grid steps (W1 is 2 when d0 is a grid date, 1 when it is not). A change is the end value minus the
start value, in basis points, computed exactly from the source's decimal text. A missing endpoint leaves the change
unavailable; no other date is used and nothing is interpolated.

Reference windows. For a measured window of span k starting at grid index m, the candidates are the windows of the
same span k ending at grid indexes m-249 to m (each ends on or before the measured start, so it precedes the measured
window; neighbouring candidates overlap each other). A candidate is eligible when both endpoints have values. At least
MINIMUM_ELIGIBLE eligible windows are required, otherwise the rank is unavailable. The rank of a measured change is
(the number of eligible windows whose absolute change is smaller + half the number with an equal absolute change)
divided by the number of eligible windows: the share of reference windows it exceeds in absolute size, ties counted
half.

Rules R1 to R4 are exploratory and descriptive. They were designed after inspecting this retained H.15 dataset, so
their frequency on comparison sessions is a description of how often each pattern appears, not a p-value, a chance
probability, causal evidence or a measure of how well they pick out events. Each rule check is met, not met, or not
evaluable (a required change or rank is unavailable).
"""
from bisect import bisect_left, bisect_right
from datetime import date
from decimal import Decimal
import hashlib

from .store import canonical, digest

RULES_VERSION = "insight-rules-0.1"
REFERENCE_WINDOWS = 250
MINIMUM_ELIGIBLE = 200
LARGE, COMPONENT_LARGE, ORDINARY, DOMINANCE = Decimal("0.9"), Decimal("0.8"), Decimal("0.5"), Decimal("0.75")
YIELDS = ("RIFLGFCM03_N.B", "RIFLGFCY02_N.B", "RIFLGFCY05_N.B", "RIFLGFCY10_N.B", "RIFLGFCY05_XII_N.B",
          "RIFLGFCY10_XII_N.B")
# Measure -> (label, [(sign, series ID)]).
MEASURES = {
    "n3m": ("3-month nominal yield", [(1, "RIFLGFCM03_N.B")]),
    "n2": ("2-year nominal yield", [(1, "RIFLGFCY02_N.B")]),
    "n5": ("5-year nominal yield", [(1, "RIFLGFCY05_N.B")]),
    "n10": ("10-year nominal yield", [(1, "RIFLGFCY10_N.B")]),
    "r5": ("5-year inflation-indexed (real) yield", [(1, "RIFLGFCY05_XII_N.B")]),
    "r10": ("10-year inflation-indexed (real) yield", [(1, "RIFLGFCY10_XII_N.B")]),
    "be5": ("5-year breakeven (nominal minus inflation-indexed)", [(1, "RIFLGFCY05_N.B"), (-1, "RIFLGFCY05_XII_N.B")]),
    "be10": ("10-year breakeven (nominal minus inflation-indexed)",
             [(1, "RIFLGFCY10_N.B"), (-1, "RIFLGFCY10_XII_N.B")]),
    "s2s10": ("2s10s slope (10-year minus 2-year)", [(1, "RIFLGFCY10_N.B"), (-1, "RIFLGFCY02_N.B")]),
}
WINDOWS = {"W1": "from the grid date before the event date to the first grid date after it",
           "W5": "from the grid date before the event date to the fifth grid date after it",
           "PRE": "from the sixth grid date before the event date to the grid date before it"}
RULES = {
    "R1": "Offsetting components: the nominal change is ordinary (rank below 0.5) while the inflation-indexed and "
          "breakeven changes are both large (rank 0.8 or more) and of opposite signs.",
    "R2": "One component dominates a large nominal change: the nominal change has rank 0.9 or more, and the "
          "component with the larger absolute change has the nominal change's sign and at least 0.75 of the two "
          "components' combined absolute change.",
    "R3": "Large slope change: the 2s10s slope change has rank 0.9 or more.",
    "R4": "Timing: the change before the event (PRE) has rank 0.9 or more while W5 has rank below 0.5, or the reverse.",
}
DEFINITIONS = {"version": RULES_VERSION, "measures": {key: [label, terms] for key, (label, terms) in MEASURES.items()},
               "windows": WINDOWS, "reference_windows": REFERENCE_WINDOWS, "minimum_eligible": MINIMUM_ELIGIBLE,
               "rank": "(smaller + 0.5 x equal absolute changes) / eligible reference windows",
               "thresholds": {"large": str(LARGE), "component_large": str(COMPONENT_LARGE),
                              "ordinary": str(ORDINARY), "dominance": str(DOMINANCE)},
               "rules": RULES}
DEFINITIONS_SHA256 = digest(DEFINITIONS)
# Rule checks evaluated for every occasion, in a fixed order.
CHECKS = ([("R1", maturity, window) for maturity in ("5", "10") for window in ("W1", "W5")] +
          [("R2", maturity, window) for maturity in ("5", "10") for window in ("W1", "W5")] +
          [("R3", None, window) for window in ("W1", "W5")] + [("R4", series, None) for series in ("n2", "n3m")])


class Grid:
    """Grid dates and each yield series' values (Decimal percent or None) and source texts on them."""

    def __init__(self, series: dict[str, list[tuple[date, str | None]]]):
        self.dates = sorted({day for rows in series.values() for day, _ in rows})
        self.index = {day: i for i, day in enumerate(self.dates)}
        self.texts = {sid: dict(rows) for sid, rows in series.items()}
        self.values = {sid: {day: Decimal(text) if text is not None else None for day, text in rows}
                       for sid, rows in series.items()}
        self._arrays: dict[str, list] = {}

    def value(self, measure: str, i: int) -> Decimal | None:
        if measure not in self._arrays:  # Each measure's value on every grid date, computed once.
            array = []
            for day in self.dates:
                total = Decimal(0)
                for sign, series_id in MEASURES[measure][1]:
                    value = self.values[series_id].get(day)
                    if value is None:
                        total = None
                        break
                    total += sign * value
                array.append(total)
            self._arrays[measure] = array
        return self._arrays[measure][i]

    def change(self, measure: str, i: int, j: int) -> Decimal | None:
        start, end = self.value(measure, i), self.value(measure, j)
        return None if start is None or end is None else (end - start) * 100


def endpoints(grid: Grid, event: date) -> dict:
    """B6, B1, A1 and A5 as grid indexes, or why they cannot be set."""
    before = bisect_left(grid.dates, event)  # Grid dates before the event date: indexes 0 .. before-1.
    after = bisect_right(grid.dates, event)  # The first grid date after it.
    if before < 6:
        return {"problem": "not_enough_history", "detail": "Fewer than six grid dates precede the event date."}
    if after + 4 >= len(grid.dates):
        last = grid.dates[-1].isoformat() if grid.dates else None
        return {"problem": "window_not_in_data",
                "detail": f"The retained data end on {last}; the fifth grid date after the event date is not in them."}
    return {"B6": before - 6, "B1": before - 1, "A1": after, "A5": after + 4, "event_on_grid": event in grid.index}


def window_span(points: dict, window: str) -> tuple[int, int]:
    return {"W1": (points["B1"], points["A1"]), "W5": (points["B1"], points["A5"]),
            "PRE": (points["B6"], points["B1"])}[window]


def rank(value: Decimal, reference: list[Decimal]) -> dict:
    size = abs(value)
    smaller = sum(1 for item in reference if abs(item) < size)
    equal = sum(1 for item in reference if abs(item) == size)
    return {"smaller": smaller, "equal": equal, "eligible": len(reference),
            "rank": str(((Decimal(smaller) + Decimal(equal) / 2) / len(reference)).quantize(Decimal("0.0001")))}


def measured(grid: Grid, measure: str, start: int, end: int) -> dict:
    """One measure over one window: endpoints with their source values, the change, and its reference rank."""
    span = end - start
    endpoints_ = []
    for index in (start, end):
        day = grid.dates[index]
        endpoints_.append({"date": day.isoformat(),
                           "values": [{"series_id": series_id, "sign": sign, "text": grid.texts[series_id].get(day)}
                                      for sign, series_id in MEASURES[measure][1]]})
    entry = {"measure": measure, "span": span, "start": endpoints_[0], "end": endpoints_[1], "change_bp": None,
             "reference": None, "problem": None}
    change = grid.change(measure, start, end)
    if change is None:
        entry["problem"] = "A required observation at an endpoint is missing (no value in the source)."
        return entry
    entry["change_bp"] = _text(change)
    candidates = [j for j in range(start - REFERENCE_WINDOWS + 1, start + 1) if j - span >= 0]
    reference = [grid.change(measure, j - span, j) for j in candidates]
    usable = [item for item in reference if item is not None]
    entry["reference"] = {"candidates": len(candidates), "first_end": grid.dates[candidates[0]].isoformat()
                          if candidates else None, "last_end": grid.dates[candidates[-1]].isoformat()
                          if candidates else None}
    if len(usable) < MINIMUM_ELIGIBLE:
        entry["reference"]["eligible"] = len(usable)
        entry["problem"] = (f"Only {len(usable)} of {len(candidates)} reference windows are usable; at least "
                            f"{MINIMUM_ELIGIBLE} are required for a rank.")
        return entry
    entry["reference"].update(rank(change, usable))
    return entry


def _text(value: Decimal) -> str:
    """A change in bp as exact text: 12, -3.5, 0."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "0") else text


def _rank(entry: dict | None) -> Decimal | None:
    return Decimal(entry["reference"]["rank"]) if entry and (entry.get("reference") or {}).get("rank") else None


def _check(rule: str, subject: str | None, window: str | None, table: dict) -> dict:
    """One rule check from the measured table: met, not met or not evaluable, with the measures it read."""
    def get(measure: str, which: str) -> dict | None:
        return table.get(f"{measure}:{which}")
    base = {"rule": rule, "subject": subject, "window": window, "outcome": "not_met", "measures": [], "detail": None}
    if rule in ("R1", "R2"):
        nominal, real, breakeven = (get(f"{kind}{subject}", window) for kind in ("n", "r", "be"))
        base["measures"] = [f"n{subject}:{window}", f"r{subject}:{window}", f"be{subject}:{window}"]
        ranks = [_rank(item) for item in (nominal, real, breakeven)]
        if any(item is None for item in ranks):
            return {**base, "outcome": "not_evaluable", "detail": "A required change or rank is unavailable."}
        dn, dr, db = (Decimal(item["change_bp"]) for item in (nominal, real, breakeven))
        if rule == "R1":
            met = ranks[0] < ORDINARY and ranks[1] >= COMPONENT_LARGE and ranks[2] >= COMPONENT_LARGE and dr * db < 0
            return {**base, "outcome": "met" if met else "not_met"}
        total = abs(dr) + abs(db)
        if ranks[0] < LARGE or dn == 0:
            return base
        if total == 0:
            return {**base, "detail": "Both components are zero, so no share is defined."}
        larger, name = (dr, "inflation-indexed") if abs(dr) >= abs(db) else (db, "breakeven")
        share = abs(larger) / total
        met = share >= DOMINANCE and larger * dn > 0
        return {**base, "outcome": "met" if met else "not_met",
                "detail": {"dominant": name, "share": str(share.quantize(Decimal("0.01")))}}
    if rule == "R3":
        slope = get("s2s10", window)
        base["measures"] = [f"s2s10:{window}", f"n2:{window}", f"n10:{window}"]
        if _rank(slope) is None:
            return {**base, "outcome": "not_evaluable", "detail": "The slope change or its rank is unavailable."}
        return {**base, "outcome": "met" if _rank(slope) >= LARGE else "not_met"}
    before, after = get(subject, "PRE"), get(subject, "W5")
    base["measures"] = [f"{subject}:PRE", f"{subject}:W5"]
    if _rank(before) is None or _rank(after) is None:
        return {**base, "outcome": "not_evaluable", "detail": "A required change or rank is unavailable."}
    if _rank(before) >= LARGE and _rank(after) < ORDINARY:
        return {**base, "outcome": "met", "detail": {"direction": "before"}}
    if _rank(before) < ORDINARY and _rank(after) >= LARGE:
        return {**base, "outcome": "met", "detail": {"direction": "after"}}
    return base


def evaluate(grid: Grid, event: date) -> dict:
    """Every measure over every window around one event date, and every rule check. Deterministic; no I/O."""
    points = endpoints(grid, event)
    if "problem" in points:
        return {"state": "unavailable", "problem": points["problem"], "detail": points["detail"], "windows": {},
                "table": {}, "checks": []}
    windows = {}
    for window in WINDOWS:
        start, end = window_span(points, window)
        windows[window] = {"start": grid.dates[start].isoformat(), "end": grid.dates[end].isoformat(),
                           "span": end - start}
    table = {}
    for measure in MEASURES:
        for window in WINDOWS:
            if window == "PRE" and measure not in ("n2", "n3m"):
                continue
            start, end = window_span(points, window)
            table[f"{measure}:{window}"] = measured(grid, measure, start, end)
    checks = [_check(rule, subject, window, table) for rule, subject, window in CHECKS]
    evaluable = [check for check in checks if check["outcome"] != "not_evaluable"]
    state = "unavailable" if not evaluable else "checked"
    return {"state": state, "problem": None if evaluable else "no_rule_evaluable",
            "detail": None if evaluable else "No rule check could be evaluated: required values are missing.",
            "event_on_grid": points["event_on_grid"], "windows": windows, "table": table, "checks": checks}


def inputs(grid: Grid, event: date) -> dict | None:
    """The exact observations an evaluation reads: every yield series' grid text from the earliest reference start to
    the last window end. None when the windows cannot be set."""
    points = endpoints(grid, event)
    if "problem" in points:
        return None
    starts = [window_span(points, window) for window in WINDOWS]
    low = max(0, min(start - REFERENCE_WINDOWS + 1 - (end - start) for start, end in starts))
    high = points["A5"]
    return {series_id: [[grid.dates[i].isoformat(), grid.texts[series_id].get(grid.dates[i])]
                        for i in range(low, high + 1)] for series_id in YIELDS}


def inputs_sha256(observations: dict) -> str:
    return hashlib.sha256(canonical(observations).encode("utf-8")).hexdigest()


def comparison(grid: Grid, excluded: set[date], seed: str, size: int, first: date, last: date) -> dict:
    """How often each rule check is met on comparison sessions: grid dates in [first, last] chosen in the order of
    SHA-256(seed|date), skipping any whose B6..A5 span contains an excluded date (a retained event date). Descriptive
    counts with their denominators; the sessions are not news-free."""
    candidates = []
    for day in grid.dates:
        if not first <= day <= last:
            continue
        points = endpoints(grid, day)
        if "problem" in points or any(grid.dates[points["B6"]] <= other <= grid.dates[points["A5"]]
                                      for other in excluded):
            continue
        candidates.append(day)
    chosen = sorted(sorted(candidates, key=lambda day: hashlib.sha256(f"{seed}|{day.isoformat()}".encode()).hexdigest())
                    [:size])
    counts = {f"{rule}:{subject}:{window}": {"met": 0, "evaluable": 0} for rule, subject, window in CHECKS}
    any_met = any_evaluable = 0
    for day in chosen:
        result = evaluate(grid, day)
        met = False
        evaluable = False
        for check in result["checks"]:
            key = f"{check['rule']}:{check['subject']}:{check['window']}"
            if check["outcome"] != "not_evaluable":
                counts[key]["evaluable"] += 1
                evaluable = True
            if check["outcome"] == "met":
                counts[key]["met"] += 1
                met = True
        any_met += met
        any_evaluable += evaluable
    return {"seed": seed, "size": size, "range": [first.isoformat(), last.isoformat()], "candidates": len(candidates),
            "sessions": [day.isoformat() for day in chosen], "checks": counts,
            "any": {"met": any_met, "evaluable": any_evaluable}}


def check_key(check: dict) -> str:
    return f"{check['rule']}:{check['subject']}:{check['window']}"

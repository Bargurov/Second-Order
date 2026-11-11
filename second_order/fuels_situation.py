"""Situation Now arithmetic for the fuels page (fuels-situation).

Change windows over the dates on which Brent, gasoline and diesel all have a value, and the exact split of the
basket's change. The split is an accounting identity, not a cause:
- change in basket = change in Brent + change in crack;
- change in basket = 28 x change in gasoline + 14 x change in diesel (the 2-to-1 weights per barrel of crude input).

Arithmetic is exact (Fraction). Rounded text is for display only and never feeds later arithmetic. Nothing here
reads a file or reaches a network."""
import calendar
from datetime import date, timedelta
from fractions import Fraction

from second_order.fuels_crack import basket_value, common_dates, exact_text, shown

ENGINE_VERSION = "fuels-situation-0.1"
WEEK_TOLERANCE_DAYS = 3
MONTH_TOLERANCE_DAYS = 5
STALE_DAYS = 10
LABELS = ("unchanged", "offsetting", "mostly_crude", "mostly_crack", "both")

_ROLES = ("brent", "wti", "gasoline", "diesel", "henry_hub")
_SERIES = ("brent", "gasoline", "diesel")
_PLACES = {"brent": 2, "gasoline": 3, "diesel": 3, "basket": 2, "crack": 2}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_before(day: date) -> date:
    """The same day of the previous month, clamped to that month's length."""
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def split_label(crude: Fraction, crack: Fraction) -> str:
    if crude == 0 and crack == 0:
        return "unchanged"
    if crude * crack < 0:
        return "offsetting"
    share = abs(crude) / (abs(crude) + abs(crack))
    if share >= Fraction(2, 3):
        return "mostly_crude"
    if share <= Fraction(1, 3):
        return "mostly_crack"
    return "both"


def _date_text(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _pair(value: Fraction, places: int) -> dict:
    return {"value": exact_text(value), "shown": shown(value, places)}


def _levels(inputs: dict, day: date) -> dict[str, Fraction]:
    values = {name: inputs[name][day] for name in _SERIES}
    values["basket"] = basket_value(values["gasoline"], values["diesel"])
    values["crack"] = values["basket"] - values["brent"]
    return values


def _row(name: str, old: Fraction, new: Fraction) -> dict:
    places = _PLACES[name]
    change = new - old
    pct = None
    if name != "crack" and old > 0:
        pct = {"shown": shown(change / old * 100, 1)}
    return {"from": _pair(old, places), "to": _pair(new, places), "change": _pair(change, places), "pct": pct}


def _split(old: dict, new: dict) -> dict:
    crude = new["brent"] - old["brent"]
    crack = new["crack"] - old["crack"]
    return {"crude": _pair(crude, 2), "crack": _pair(crack, 2),
            "basket": _pair(new["basket"] - old["basket"], 2),
            "gasoline_part": _pair(28 * (new["gasoline"] - old["gasoline"]), 2),
            "diesel_part": _pair(14 * (new["diesel"] - old["diesel"]), 2),
            "label": split_label(crude, crack)}


def _window(window_id: str, inputs: dict, dates: list[date], latest: date, target: date | None,
            tolerance: int | None) -> dict:
    base = {"id": window_id, "state": "unavailable", "reason": None,
            "target": target.isoformat() if target else None, "from": None, "to": latest.isoformat(),
            "rows": None, "split": None}
    if target is None:
        earlier = [day for day in dates if day < latest]
        if not earlier:
            return {**base, "reason": "There is no earlier common observation"}
        start = earlier[-1]
    else:
        earlier = [day for day in dates if day <= target]
        if not earlier or (target - earlier[-1]).days > tolerance:
            return {**base, "reason": f"No common observation within {tolerance} days before {_date_text(target)}"}
        start = earlier[-1]
    old, new = _levels(inputs, start), _levels(inputs, latest)
    rows = {name: _row(name, old[name], new[name]) for name in (*_SERIES, "basket", "crack")}
    return {**base, "state": "computed", "from": start.isoformat(), "rows": rows, "split": _split(old, new)}


def _withheld(problem: str) -> dict:
    return {"engine_version": ENGINE_VERSION, "state": "withheld", "problem": problem, "date": None,
            "age_days": None, "stale": False, "newer": [], "windows": []}


def situation(inputs: dict[str, dict[date, Fraction | None]] | None, latest: dict[str, date | None],
              retrieved_on: date | None) -> dict:
    if inputs is None:
        return _withheld("The barrel is withheld, so there is nothing to compare.")
    series = {name: inputs[name] for name in _SERIES}
    dates = common_dates(series)
    if not dates:
        return _withheld("There is no date on which Brent, gasoline and diesel all have a value.")
    newest = dates[-1]
    age = (retrieved_on - newest).days if retrieved_on else None
    # .get: a role whose series is missing, refused or withheld has no latest date (None or absent): never newer.
    newer = [{"role": role, "date": latest[role].isoformat()}
             for role in _ROLES if latest.get(role) and latest[role] > newest]
    windows = [_window("previous", series, dates, newest, None, None),
               _window("week", series, dates, newest, newest - timedelta(days=7), WEEK_TOLERANCE_DAYS),
               _window("month", series, dates, newest, month_before(newest), MONTH_TOLERANCE_DAYS)]
    return {"engine_version": ENGINE_VERSION, "state": "computed", "problem": None, "date": newest.isoformat(),
            "age_days": age, "stale": age is not None and age > STALE_DAYS, "newer": newer, "windows": windows}

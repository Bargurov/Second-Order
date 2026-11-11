"""Exact 3-2-1 crack-spread arithmetic for the fuels page (fuels-crack).

The crack here is a chosen benchmark, not a measured refinery result:
- the 2:1 gasoline-to-diesel mix approximates an output basket, not any refinery's yield;
- it is one chosen benchmark (New York Harbor products against Brent spot), not the only one;
- it is gross, before every refining cost, so it is not any refinery's profit.

Arithmetic is exact (Fraction). Rounded text is for display only and never feeds later arithmetic. Nothing here
reads a file or reaches a network."""
from datetime import date
from fractions import Fraction

from second_order import copper_producers

ENGINE_VERSION = "fuels-crack-0.1"
GALLONS_PER_BARREL = 42
BASKET_TEXT = "(2 × gasoline × 42 + 1 × diesel × 42) / 3"
CRACK_TEXT = "3-2-1 basket value − Brent"

_PLACES = {"brent": 2, "gasoline": 3, "diesel": 3}
_SERIES = ("brent", "gasoline", "diesel")


def basket_value(gasoline: Fraction, diesel: Fraction) -> Fraction:
    """Dollars per barrel of crude input. (2 * g * 42 + d * 42) / 3 equals 14 * (2 * g + d), because 42 / 3 = 14."""
    return Fraction(14) * (2 * gasoline + diesel)


def crack(gasoline: Fraction, diesel: Fraction, brent: Fraction) -> Fraction:
    return basket_value(gasoline, diesel) - brent


def exact_text(value: Fraction) -> str:
    """The plain terminating decimal of a Fraction. Raises ValueError when it does not terminate."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("the value has no terminating decimal")
    places = max(twos, fives)
    scaled = value * 10 ** places
    digits = str(abs(scaled.numerator)).rjust(places + 1, "0")
    sign = "-" if scaled < 0 else ""
    if places == 0:
        return sign + digits
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def shown(value: Fraction, places: int) -> str:
    return copper_producers.half_even(value, places)


def sign_of(value: Fraction) -> str:
    return "positive" if value > 0 else "negative" if value < 0 else "zero"


def common_dates(inputs: dict[str, dict[date, Fraction | None]]) -> list[date]:
    """Ascending dates on which every series has a value."""
    if not inputs:
        return []
    sets = [{day for day, value in series.items() if value is not None} for series in inputs.values()]
    return sorted(set.intersection(*sets))


def _pair(value: Fraction, places: int) -> dict:
    return {"value": exact_text(value), "shown": shown(value, places)}


def _day(inputs: dict[str, dict[date, Fraction | None]], day: date) -> dict[str, Fraction]:
    return {name: inputs[name][day] for name in _SERIES}


def withheld(problem: str) -> dict:
    """A barrel with no value, saying why."""
    return {"engine_version": ENGINE_VERSION, "state": "withheld", "problem": problem, "date": None,
            "previous_date": None, "inputs": None, "previous": None, "basket": None, "crack": None,
            "change": None}


def _shown_inputs(values: dict[str, Fraction]) -> dict:
    return {name: _pair(values[name], _PLACES[name]) for name in _SERIES}


def _basket_and_crack(values: dict[str, Fraction]) -> tuple[Fraction, Fraction]:
    basket = basket_value(values["gasoline"], values["diesel"])
    return basket, basket - values["brent"]


def barrel(inputs: dict[str, dict[date, Fraction | None] | None]) -> dict:
    """The latest barrel: inputs, basket, crack and the change since the previous common date."""
    missing = [name for name in _SERIES if inputs.get(name) is None]
    if missing:
        return withheld("No data for " + ", ".join(missing) + ".")
    dates = common_dates({name: inputs[name] for name in _SERIES})
    if not dates:
        return withheld("There is no date on which Brent, gasoline and diesel all have a value.")
    latest = dates[-1]
    now = _day(inputs, latest)
    basket, spread = _basket_and_crack(now)
    result = {"engine_version": ENGINE_VERSION, "state": "computed", "problem": None, "date": latest.isoformat(),
              "previous_date": None, "inputs": _shown_inputs(now), "previous": None,
              "basket": _pair(basket, 2),
              "crack": {**_pair(spread, 2), "sign": sign_of(spread)},
              "change": None}
    if len(dates) > 1:
        before = dates[-2]
        then = _day(inputs, before)
        old_basket, old_crack = _basket_and_crack(then)
        result["previous_date"] = before.isoformat()
        result["previous"] = _shown_inputs(then)
        result["change"] = {"brent": _pair(now["brent"] - then["brent"], 2),
                            "basket": _pair(basket - old_basket, 2),
                            "crack": _pair(spread - old_crack, 2)}
    return result


def crack_history(inputs: dict[str, dict[date, Fraction | None]], since: date) -> list[list[str]]:
    """[[iso date, exact crack], ...] for the common dates on or after ``since``."""
    series = {name: inputs[name] for name in _SERIES}
    rows = []
    for day in common_dates(series):
        if day >= since:
            values = _day(series, day)
            rows.append([day.isoformat(), exact_text(crack(values["gasoline"], values["diesel"], values["brent"]))])
    return rows

"""Decimal arithmetic and the status rules of the committed thesis (thesis-arithmetic).

Numbers are parsed as the sources print them and compared exactly; only display values and the derived balance, cost
and share figures are quantized, always ROUND_HALF_EVEN. Nothing here reads a file or reaches a network."""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import re

# One grouping character per value, used for every group: comma, space, no-break space, narrow no-break space or
# thin space. "23,000 000" is refused because the second group uses a different character.
_GROUPED = re.compile(r"-?\d{1,3}(?:(?P<g>[,     ])\d{3}(?:(?P=g)\d{3})*)?(?:\.\d+)?", re.ASCII)
_PLAIN = re.compile(r"-?\d+(?:\.\d+)?", re.ASCII)
_GROUPING = ",     "
_DECIMAL = re.compile(r"-?\d+(?:\.\d+)?", re.ASCII)
_PRECISION = 60


def shown_value(as_shown: str) -> Decimal:
    """Parse a figure as a source prints it. Raises ValueError for anything outside the grammar."""
    if not isinstance(as_shown, str):
        raise ValueError("a shown value is text")
    rest = as_shown
    if rest.startswith("$"):
        rest = rest[1:]
    if rest.endswith("%"):
        rest = rest[:-1]
    if not (_GROUPED.fullmatch(rest) or _PLAIN.fullmatch(rest)):
        raise ValueError(f"not a shown value: {as_shown!r}")
    for ch in _GROUPING:
        rest = rest.replace(ch, "")
    return Decimal(rest)


def decimal_of(text: str) -> Decimal:
    """A plain decimal only: -?digits with an optional fraction."""
    if not isinstance(text, str) or not _DECIMAL.fullmatch(text):
        raise ValueError(f"not a plain decimal: {text!r}")
    return Decimal(text)


def _quantize(value: Decimal, step: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return value.quantize(step, rounding=ROUND_HALF_EVEN)


def change_pct(previous: Decimal, latest: Decimal) -> Decimal:
    """Exact percentage change against the magnitude of the previous value. ZeroDivisionError when previous is 0."""
    if previous == 0:
        raise ZeroDivisionError("a previous value of zero has no percentage change")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return (latest - previous) / abs(previous) * 100


def moved(previous: Decimal, latest: Decimal) -> str:
    return "higher" if latest > previous else "lower" if latest < previous else "same"


def _direction(value: str, name: str) -> str:
    if value not in ("higher", "lower"):
        raise ValueError(f"{name} must be 'higher' or 'lower'")
    return value


def reason_state(previous: Decimal, latest: Decimal, supports_when: str, material_pct: Decimal) -> str:
    _direction(supports_when, "supports_when")
    if abs(change_pct(previous, latest)) < material_pct:  # equal to the threshold counts as a change
        return "unchanged"
    return "strengthening" if moved(previous, latest) == supports_when else "weakening"


def risk_state(previous: Decimal, latest: Decimal, grows_when: str, material_pct: Decimal) -> str:
    _direction(grows_when, "grows_when")
    if abs(change_pct(previous, latest)) < material_pct:
        return "unchanged"
    return "materialising" if moved(previous, latest) == grows_when else "receding"


def condition_state(latest: Decimal, comparator: str, threshold: Decimal) -> str:
    if comparator == "below":
        return "happened" if latest < threshold else "not_happened"  # equality has not happened
    if comparator == "above":
        return "happened" if latest > threshold else "not_happened"
    raise ValueError("comparator must be 'below' or 'above'")


def balance(supply_total: Decimal, demand_total: Decimal) -> dict:
    """Gap, its sign label, and its size in weeks of demand (52 weeks to the year), weeks quantized to 0.1.

    Weeks multiply before they divide (ruling R10): |gap| * 52 is exact, so an exact half (21 * 52 / 208 = 5.25) stays
    exact and rounds half-even; dividing first would round a non-terminating quotient and could cross the half."""
    if demand_total <= 0:
        raise ValueError("demand must be positive")
    gap = supply_total - demand_total
    label = "surplus" if gap > 0 else "deficit" if gap < 0 else "balanced"
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        weeks = _quantize(abs(gap) * 52 / demand_total, Decimal("0.1"))
    return {"gap": gap, "label": label, "weeks": weeks}


def per_unit_cost(kg_per_unit: Decimal, usd_per_tonne: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return _quantize(kg_per_unit * usd_per_tonne / 1000, Decimal("1"))


def share_pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        raise ValueError("the whole must be positive")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return _quantize(part / whole * 100, Decimal("0.1"))


def display(value: Decimal, places: int) -> str:
    """ROUND_HALF_EVEN to `places` decimals, comma thousands, a leading '-' for negatives (never '-0')."""
    if not isinstance(places, int) or isinstance(places, bool) or places < 0:
        raise ValueError("places must be a non-negative integer")
    q = _quantize(value, Decimal(1).scaleb(-places))
    if q == 0:
        q = abs(q)
    return f"{q:,.{places}f}"

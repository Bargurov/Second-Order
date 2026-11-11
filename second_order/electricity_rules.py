"""Electricity by sector: fixed comparison rules on the verified Table 7.6 extract (electricity-rules-0.1). No I/O.

Scope (fixed, part of every result's identity): each month from July 2025 to June 2026 against the same month one year
earlier, and January-June 2026 against January-June 2025. Analyzed: retail sales to the residential, commercial and
industrial sectors. Context only (never in a finding): transportation (railways only) and total retail sales. Direct
use, total end use and electric vehicle use are excluded.

Year-over-year comparison (exact decimals): change = current - prior in million kWh; percentage = change / prior x 100.
"up" when the percentage is >= +1, "down" when <= -1, otherwise "little_changed"; both bounds inclusive, decided on the
exact value (change x 100 against prior, no division). A missing observation (no row, or "Not Available") or a prior
value of zero or less makes the comparison "unavailable", with the reason. The 1% band is a fixed product filter: not
statistical significance, not calibrated and not a test of materiality. Percentages are kept to two decimals truncated
toward zero, so a shown value is on the same side of +/-1 as the exact one.

A monthly divergence finding needs at least one analyzed sector up and another down in that month; one finding per
month names all of them. The period comparison sums each sector over the six identical months of both periods before
computing the change (monthly growth rates are never averaged); a missing month in either period makes it unavailable.

Reconciliation. Residential + commercial + industrial + transportation is compared with total retail sales in every
month used. Each value is published to 0.001 million kWh, so independent rounding of the five values allows a residual
of at most 5 x 0.0005 = 0.0025 ("within_rounding"); a larger residual is "beyond_rounding" and is shown, never forced
away. Contributions to the change in total sales (each of the four sectors and the rounding residual, in million kWh)
are computed only when every month involved reconciles within rounding.
"""
from calendar import monthrange
from decimal import ROUND_DOWN, Decimal, localcontext

from .store import digest

RULES_VERSION = "electricity-rules-0.1"
ANALYZED = ("ESRCPUS", "ESCCPUS", "ESICPUS")
CONTEXT = ("ESACPUS", "ESTCPUS")
SECTORS = ("ESRCPUS", "ESCCPUS", "ESICPUS", "ESACPUS")  # Their sum is the total (Table 7.6 footnote f).
TOTAL = "ESTCPUS"
EXCLUDED = ("ELDUPUS", "ELTCPUS", "ESVHPUS")
CODES = ANALYZED + CONTEXT
LABELS = {"ESRCPUS": "Residential", "ESCCPUS": "Commercial", "ESICPUS": "Industrial",
          "ESACPUS": "Transportation (railways only)", "ESTCPUS": "Total retail sales",
          "ELDUPUS": "Direct use", "ELTCPUS": "Total end use", "ESVHPUS": "Electric vehicle use"}
KEYS = {"ESRCPUS": "residential", "ESCCPUS": "commercial", "ESICPUS": "industrial", "ESACPUS": "transportation",
        "ESTCPUS": "total"}
THRESHOLD = Decimal("1")
TOLERANCE = Decimal("0.0025")
SCOPE = {
    "months": {"first": "2025-07", "last": "2026-06"},
    "comparison": "same month one year earlier",
    "period": {"current": {"first": "2026-01", "last": "2026-06"}, "prior": {"first": "2025-01", "last": "2025-06"}},
}
DEFINITIONS = {
    "version": RULES_VERSION,
    "scope": SCOPE,
    "analyzed": {code: LABELS[code] for code in ANALYZED},
    "context": {code: LABELS[code] for code in CONTEXT},
    "excluded": {code: LABELS[code] for code in EXCLUDED},
    "values": "Retail sales in million kWh as published in the CSV (three decimals), exact decimal arithmetic.",
    "change": "current minus prior, million kWh; percentage = change / prior x 100",
    "classes": {"up": "percentage >= +1", "down": "percentage <= -1", "little_changed": "otherwise",
                "unavailable": "a missing observation, or a prior value of zero or less"},
    "threshold": "1% is a fixed, transparent product filter: not statistical significance, not empirically "
                 "calibrated, not proof of materiality.",
    "percent_display": "two decimals, truncated toward zero",
    "monthly_finding": "at least one analyzed sector up and another down in the same month; one finding per month",
    "period": "sum each sector over identical complete periods, then compare; growth rates are never averaged",
    "reconciliation": {"identity": "residential + commercial + industrial + transportation = total retail sales",
                       "tolerance_million_kwh": str(TOLERANCE),
                       "basis": "five values each published to 0.001; independent rounding allows 5 x 0.0005"},
    "contributions": "changes of the four sectors and the rounding residual, only when every month involved "
                     "reconciles within rounding",
}
DEFINITIONS_SHA256 = digest(DEFINITIONS)


def _shift(key: str, months: int) -> str:
    index = int(key[:4]) * 12 + int(key[5:]) - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def span(first: str, last: str) -> list[str]:
    out, key = [], first
    while key <= last:
        out.append(key)
        key = _shift(key, 1)
    return out


def prior(key: str) -> str:
    return _shift(key, -12)


def months() -> list[str]:
    return span(SCOPE["months"]["first"], SCOPE["months"]["last"])


def period_months(which: str) -> list[str]:
    return span(SCOPE["period"][which]["first"], SCOPE["period"][which]["last"])


def window() -> list[str]:
    """Every month the scope reads: the compared months, their prior-year months and both periods."""
    keys = set(months()) | {prior(key) for key in months()} | set(period_months("current")) | \
        set(period_months("prior"))
    return sorted(keys)


def text(value: Decimal) -> str:
    return format(value, "f")


def percent_text(change: Decimal, base: Decimal) -> str:
    """change / base x 100, two decimals truncated toward zero ("-0.00" written "0.00")."""
    with localcontext() as context:
        context.prec = 50
        shown = (change * 100 / base).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return "0.00" if shown == 0 else text(shown)


def classify(change: Decimal, base: Decimal) -> str:
    """Exact and inclusive: change x 100 >= base is up, <= -base is down (base > 0)."""
    scaled = change * 100
    if scaled >= THRESHOLD * base:
        return "up"
    if scaled <= -THRESHOLD * base:
        return "down"
    return "little_changed"


def compare(current: Decimal | None, earlier: Decimal | None, current_missing: str | None = None,
            earlier_missing: str | None = None) -> dict:
    """One year-over-year comparison of two values (or of two period sums)."""
    out = {"current": None if current is None else text(current), "prior": None if earlier is None else text(earlier),
           "change": None, "percent": None, "class": "unavailable", "reason": None}
    if current is None or earlier is None:
        out["reason"] = "; ".join(item for item in (current_missing, earlier_missing) if item)
        return out
    if earlier <= 0:
        out["reason"] = f"the prior value {text(earlier)} is not a positive denominator"
        return out
    change = current - earlier
    return {**out, "change": text(change), "percent": percent_text(change, earlier), "class": classify(change, earlier),
            "reason": None}


def _value(values: dict, code: str, key: str) -> tuple[Decimal | None, str | None]:
    raw = values[code].get(key)
    if raw is None:
        return None, f"no {key} row"
    if raw == "Not Available":
        return None, f"{key} not available"
    return Decimal(raw), None


def divergence(comparisons: dict) -> dict:
    groups = {name: [code for code in ANALYZED if comparisons[code]["class"] == name]
              for name in ("up", "down", "little_changed", "unavailable")}
    return {**groups, "finding": bool(groups["up"]) and bool(groups["down"])}


def reconcile(values: dict, key: str) -> dict:
    """One month's sector sum against the total, with the residual (total minus the sum)."""
    parts = [_value(values, code, key)[0] for code in SECTORS]
    total = _value(values, TOTAL, key)[0]
    if total is None or any(part is None for part in parts):
        return {"month": key, "state": "unavailable", "sum": None, "total": None, "residual": None}
    summed = sum(parts, Decimal(0))
    residual = total - summed
    return {"month": key, "state": "within_rounding" if abs(residual) <= TOLERANCE else "beyond_rounding",
            "sum": text(summed), "total": text(total), "residual": text(residual)}


def contributions(values: dict, current: list[str], earlier: list[str]) -> dict:
    """How the four sectors' changes make up the change in total sales over the given months, when all reconcile."""
    checks = [reconcile(values, key) for key in current + earlier]
    blocked = [item["month"] for item in checks if item["state"] != "within_rounding"]
    if blocked:
        return {"state": "unavailable", "detail": "not every month involved reconciles within rounding: "
                + ", ".join(blocked), "sectors": None, "total_change": None, "residual_change": None,
                "analyzed_change": None}

    def change(code):
        return sum((_value(values, code, key)[0] for key in current), Decimal(0)) - \
            sum((_value(values, code, key)[0] for key in earlier), Decimal(0))
    sectors = {code: change(code) for code in SECTORS}
    total = change(TOTAL)
    return {"state": "computed", "detail": None, "sectors": {code: text(value) for code, value in sectors.items()},
            "analyzed_change": text(sum((sectors[code] for code in ANALYZED), Decimal(0))),
            "total_change": text(total), "residual_change": text(total - sum(sectors.values(), Decimal(0)))}


def month_result(values: dict, key: str) -> dict:
    earlier = prior(key)
    comparisons = {}
    for code in CODES:
        current, current_missing = _value(values, code, key)
        before, before_missing = _value(values, code, earlier)
        comparisons[code] = compare(current, before, current_missing, before_missing)
    return {"month": key, "prior": earlier, "days": monthrange(int(key[:4]), int(key[5:]))[1],
            "prior_days": monthrange(int(earlier[:4]), int(earlier[5:]))[1], "comparisons": comparisons,
            "divergence": divergence(comparisons),
            "reconciliation": [reconcile(values, key), reconcile(values, earlier)],
            "contributions": contributions(values, [key], [earlier])}


def period_result(values: dict) -> dict:
    current, earlier = period_months("current"), period_months("prior")
    comparisons = {}
    for code in CODES:
        found = {key: _value(values, code, key) for key in current + earlier}
        missing = [reason for _, reason in found.values() if reason]
        if missing:
            comparisons[code] = compare(None, None, "; ".join(missing))
            continue
        comparisons[code] = compare(sum((found[key][0] for key in current), Decimal(0)),
                                    sum((found[key][0] for key in earlier), Decimal(0)))
    days = sum(monthrange(int(key[:4]), int(key[5:]))[1] for key in current)
    prior_days = sum(monthrange(int(key[:4]), int(key[5:]))[1] for key in earlier)
    return {"current": current, "prior": earlier, "days": days, "prior_days": prior_days, "comparisons": comparisons,
            "divergence": divergence(comparisons), "contributions": contributions(values, current, earlier)}


def compute(values: dict) -> dict:
    """Every compared month, the period, the reconciliation of every month read, and the counts."""
    monthly = [month_result(values, key) for key in months()]
    period = period_result(values)
    checks = [reconcile(values, key) for key in window()]
    residuals = [abs(Decimal(item["residual"])) for item in checks if item["residual"] is not None]
    classes = {name: sum(1 for row in monthly for code in ANALYZED if row["comparisons"][code]["class"] == name)
               for name in ("up", "down", "little_changed", "unavailable")}
    return {"rules_version": RULES_VERSION, "months": monthly, "period": period,
            "reconciliation": {"months": checks, "tolerance": str(TOLERANCE),
                               "counts": {state: sum(1 for item in checks if item["state"] == state)
                                          for state in ("within_rounding", "beyond_rounding", "unavailable")},
                               "max_abs_residual": text(max(residuals)) if residuals else None},
            "counts": {"months": len(monthly), "monthly_findings": sum(1 for row in monthly
                                                                       if row["divergence"]["finding"]),
                       "period_finding": period["divergence"]["finding"], "sector_months": classes}}

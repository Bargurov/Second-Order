"""Cross-source comparisons (cross-source-rules-0.1): EIA Table 7.6 retail sales set beside G.17 output rates for the
same periods. Descriptive only; no I/O.

Periods. The fourth quarter of 2023, 2024 and 2025 against the previous fourth quarter, and each 12-month period that
a retained G.17 release prints (its latest month against the same month a year earlier). A period is never completed
with a different month.

EIA side (exact decimals). A fourth quarter is the October-December total of that year; all three months must have a
value in both years. A 12-month period compares that month with the same month a year earlier. Change = current - prior
in million kWh; percentage = change / prior x 100, kept to two decimals truncated toward zero. A month the retained
file does not reach is "not covered"; a month inside its range without a value ("Not Available" or no row) makes the
comparison "unavailable", as does a prior value of zero or less. Annual rows are never used.

G.17 side. The published percent change of a seasonally adjusted output index, as printed (one decimal). Fourth
quarter: the latest retained release printing that year for the row; every retained release's value is listed beside
it. 12-month: the release whose 12-month column is exactly that month, with that month's marker in the release.

Signs. A sign-only description of the two reported changes: "same_sign", "opposite_signs", or "no_direction" when the
EIA change is exactly zero or G.17 prints 0.0 (or -0.0), whose unrounded value could be on either side. There is no
magnitude threshold; these are not the +/-1% categories of Electricity by sector. Growth rates are never subtracted or
combined into a score, factor or estimate.

The customer breakdown decomposes EIA total retail sales only: each class's change in million kWh plus the rounding
residual equals the total's change, computed only when every month involved reconciles within 0.0025 million kWh
(electricity_rules.contributions). It does not show what drove G.17 utility output.
"""
from decimal import Decimal

from . import electricity_rules
from .store import digest

RULES_VERSION = "cross-source-rules-0.1"
INDUSTRIAL, TOTAL = "ESICPUS", "ESTCPUS"
CLASSES = ("ESRCPUS", "ESCCPUS", "ESICPUS", "ESACPUS")
CODES = CLASSES + (TOTAL,)
Q4_YEARS = (2023, 2024, 2025)
SCOPE = {"fourth_quarters": list(Q4_YEARS),
         "twelve_month": "each 12-month period printed in a retained G.17 release's 12-month column"}
COMPARISONS = {
    "industrial_vs_manufacturing": {"eia": INDUSTRIAL, "g17": "manufacturing"},
    "utility_output_and_customers": {"eia": TOTAL, "g17": "electric"},
}
DEFINITIONS = {
    "version": RULES_VERSION,
    "scope": SCOPE,
    "eia_fourth_quarter": "October-December total of the year against the same months a year earlier; all three months "
                          "required in both years",
    "eia_month": "the month's value against the same month a year earlier",
    "eia_percent": "change / prior x 100, two decimals truncated toward zero",
    "eia_unavailable": "a month inside the file's range without a value, or a prior total of zero or less",
    "eia_not_covered": "a month outside the range of the retained file",
    "g17_value": "published percent change of a seasonally adjusted index as printed; a printed 0.0 or -0.0 has no "
                 "direction",
    "release_selection": {"fourth_quarter": "the latest retained release printing the year for the row",
                          "twelve_month": "the release whose 12-month column is exactly that month"},
    "signs": "sign-only: same_sign, opposite_signs, or no_direction (an exact zero EIA change or a printed G.17 0.0); "
             "no magnitude threshold; not the +/-1% categories of Electricity by sector",
    "customer_breakdown": "decomposes EIA total retail sales only (four classes and the rounding residual), when every "
                          "month involved reconciles within 0.0025 million kWh; not a decomposition of G.17 output",
    "not_computed": "no difference of growth rates, efficiency score, conversion factor or causal estimate",
    "comparisons": COMPARISONS,
}
DEFINITIONS_SHA256 = digest(DEFINITIONS)


def shift(key: str, months: int) -> str:
    index = int(key[:4]) * 12 + int(key[5:]) - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def fourth_quarter(year: int) -> list[str]:
    return [f"{year:04d}-{month:02d}" for month in (10, 11, 12)]


def eia_months(twelve: list[str]) -> list[str]:
    """Every month the EIA side reads: both fourth quarters of each year, and each 12-month period's two months."""
    keys = set()
    for year in Q4_YEARS:
        keys |= set(fourth_quarter(year)) | set(fourth_quarter(year - 1))
    for key in twelve:
        keys |= {key, shift(key, -12)}
    return sorted(keys)


def sign(value: Decimal | None) -> int | None:
    return None if value is None else (0 if value == 0 else (1 if value > 0 else -1))


def _state(values: dict, coverage: dict, code: str, key: str) -> tuple[Decimal | None, str | None, str]:
    """(value, reason, state): state is "value", "not_covered" (outside the file) or "unavailable" (inside, no value)."""
    span = coverage[code]
    if key < span["monthly_first"] or key > span["monthly_last"]:
        return None, f"{key} is outside the retained file ({span['monthly_first']} to {span['monthly_last']})", \
            "not_covered"
    raw = values[code].get(key)
    if raw is None:
        return None, f"no {key} row", "unavailable"
    if raw == "Not Available":
        return None, f"{key} not available", "unavailable"
    return Decimal(raw), None, "value"


def eia_change(values: dict, coverage: dict, code: str, current: list[str], prior: list[str]) -> dict:
    """The change of a month or quarter total against the same months a year earlier."""
    found = {key: _state(values, coverage, code, key) for key in current + prior}
    outside = [key for key, (_, _, state) in found.items() if state == "not_covered"]
    missing = [reason for _, reason, state in found.values() if state == "unavailable"]
    out = {"code": code, "months": current, "prior_months": prior, "current": None, "prior": None, "change": None,
           "percent": None, "sign": None, "state": "computed", "reason": None}
    if outside:
        span = coverage[code]
        return {**out, "state": "not_covered", "reason": f"outside the retained file ({span['monthly_first']} to "
                                                         f"{span['monthly_last']}): {', '.join(outside)}"}
    if missing:
        return {**out, "state": "unavailable", "reason": "; ".join(missing)}
    now = sum((found[key][0] for key in current), Decimal(0))
    before = sum((found[key][0] for key in prior), Decimal(0))
    out.update(current=electricity_rules.text(now), prior=electricity_rules.text(before))
    if before <= 0:
        return {**out, "state": "unavailable", "reason": f"the prior total {electricity_rules.text(before)} is not a "
                                                           "positive denominator"}
    change = now - before
    return {**out, "change": electricity_rules.text(change), "percent": electricity_rules.percent_text(change, before),
            "sign": sign(change)}


def g17_value(extracts: list[dict], row: str, period: dict) -> dict:
    """The selected G.17 value for a period, with its release, column and marker, and every vintage beside it."""
    if period["kind"] == "fourth_quarter":
        year = str(period["year"])
        printing = [extract for extract in extracts if year in extract["rows"][row]["fourth_quarter"]]
        vintages = [{"release": extract["release"], "release_date_as_stated": extract["release_date_as_stated"],
                     "value": extract["rows"][row]["fourth_quarter"][year]["value"]} for extract in printing]
        chosen = printing[-1] if printing else None
        cell = chosen["rows"][row]["fourth_quarter"][year] if chosen else None
        marker = None
    else:
        matching = [extract for extract in extracts if extract["rows"][row]["twelve_month"]["period"] == period["key"]]
        vintages = [{"release": extract["release"], "release_date_as_stated": extract["release_date_as_stated"],
                     "value": extract["rows"][row]["twelve_month"]["value"]} for extract in matching]
        chosen = matching[-1] if matching else None
        cell = chosen["rows"][row]["twelve_month"] if chosen else None
        marker = cell["marker"] if cell else None
    if chosen is None:
        return {"state": "not_printed", "value": None, "sign": None, "vintages": [], "release": None}
    value = cell["value"]
    return {"state": "printed" if value is not None else "blank", "value": value,
            "sign": None if value is None else sign(Decimal(value)), "release": chosen["release"],
            "release_date_as_stated": chosen["release_date_as_stated"], "marker": marker, "column": cell["column"],
            "path": chosen["rows"][row]["path"], "naics": chosen["rows"][row]["naics"],
            "sha256": chosen["source"]["sha256"], "url": chosen["source"]["url"],
            "extract_id": chosen["extract_id"], "vintages": vintages,
            "vintages_differ": len({item["value"] for item in vintages}) > 1}


def pair(eia: dict, g17: dict) -> str:
    """A sign-only description of two reported changes (see the module notes)."""
    if eia["state"] != "computed":
        return eia["state"]
    if g17["state"] != "printed":
        return "not_printed" if g17["state"] == "not_printed" else "unavailable"
    if eia["sign"] == 0 or g17["sign"] == 0:
        return "no_direction"
    return "same_sign" if eia["sign"] == g17["sign"] else "opposite_signs"


def periods(extracts: list[dict]) -> list[dict]:
    """The fixed fourth quarters, then each 12-month period a retained release prints, in time order."""
    out = [{"key": f"{year}-Q4", "kind": "fourth_quarter", "year": year, "months": fourth_quarter(year),
            "prior_months": fourth_quarter(year - 1)} for year in Q4_YEARS]
    twelve = sorted({extract["rows"]["manufacturing"]["twelve_month"]["period"] for extract in extracts} |
                    {extract["rows"]["electric"]["twelve_month"]["period"] for extract in extracts})
    out += [{"key": key, "kind": "twelve_month", "months": [key], "prior_months": [shift(key, -12)]} for key in twelve]
    return out


def compute(extracts: list[dict], values: dict, coverage: dict) -> dict:
    rows = periods(extracts)
    industrial, utility = [], []
    for period in rows:
        current, prior = period["months"], period["prior_months"]
        eia = eia_change(values, coverage, INDUSTRIAL, current, prior)
        g17 = g17_value(extracts, "manufacturing", period)
        industrial.append({"period": period["key"], "kind": period["kind"], "eia": eia, "g17": g17,
                           "signs": pair(eia, g17)})
        total = eia_change(values, coverage, TOTAL, current, prior)
        classes = {code: eia_change(values, coverage, code, current, prior) for code in CLASSES}
        breakdown = electricity_rules.contributions(values, current, prior) if total["state"] == "computed" else \
            {"state": "unavailable", "detail": total["reason"], "sectors": None, "total_change": None,
             "residual_change": None, "analyzed_change": None}
        utility.append({"period": period["key"], "kind": period["kind"], "g17": g17_value(extracts, "electric", period),
                        "eia_total": total, "eia_classes": classes, "breakdown": breakdown})
    counts = {name: sum(1 for row in industrial if row["signs"] == name)
              for name in ("same_sign", "opposite_signs", "no_direction", "not_covered", "unavailable", "not_printed")}
    return {"rules_version": RULES_VERSION, "periods": [{key: value for key, value in period.items()}
                                                        for period in rows],
            "industrial_vs_manufacturing": industrial, "utility_output_and_customers": utility,
            "counts": {"periods": len(rows), "industrial_signs": counts}}

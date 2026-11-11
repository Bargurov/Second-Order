"""Viewer text for the electricity findings (electricity-text-0.1): fixed templates filled from a verified result.

Monthly cards: one per month with at least one analyzed sector up and another down, latest month first. The period
card, when its comparison diverges, follows them. Every card states the observations (the three analyzed sectors and,
as context, transportation and total retail sales), what the comparison adds to the total, an interpretation labelled
as not observed, the contributions to the change in total sales when reconciliation permits, and the six disclosures.
"""
from calendar import month_name
from decimal import Decimal

from . import electricity_rules as rules

TEXT_VERSION = "electricity-text-0.1"
ORDER = "One card per month in which at least one analyzed sector was up and another down; latest month first, then " \
        "the January-June comparison."
DISCLOSURES = (
    "Retail sales of electricity to ultimate customers, not total electricity consumption: direct use (such as "
    "electricity generated and used on site) is not included.",
    "Not weather-adjusted and not calendar-adjusted.",
    "No price normalization and no inference about economic output.",
    "Whether an observation is preliminary is not marked in the retained data.",
    "A single retained acquisition of the data, not a revision history.",
    "No cause is established.",
)
LIMITATIONS = (
    "Residential, commercial and industrial sales include electricity used to operate and move electric vehicles "
    "(Table 7.6 footnote b). Electric vehicle use is a separate estimate; it is neither added nor subtracted here.",
    "Transportation covers sales to public railroads and railway systems only (footnote e), not electricity used by "
    "road vehicles. It is shown as context and never enters a finding.",
    "Industrial retail sales leave out direct use (self-generated electricity used on site, footnote g), so they are "
    "not total industrial electricity use.",
    "The sectors are EIA classes of service (footnotes a to d). The section notes on coverage and the sources were not "
    "retained, so billing-period conventions are not established here.",
    "The 1% band is a fixed product filter: not statistical significance, not an empirically calibrated threshold and "
    "not proof of materiality.",
    "The comparison scope is fixed. It does not move when newer data appear, and the last month in the retained file "
    "is not necessarily the latest month EIA has published since.",
    "The CSV states no edition. The retained PDF prints the September 2026 edition; that edition is not assigned to "
    "the CSV, and values agreeing between them would show consistency, not a shared vintage.",
)


def month_label(key: str) -> str:
    return f"{month_name[int(key[5:])]} {key[:4]}"


def period_label(keys: list[str]) -> str:
    first, last = keys[0], keys[-1]
    return f"{month_name[int(first[5:])]}–{month_name[int(last[5:])]} {first[:4]}"


def _names(codes: list[str]) -> str:
    names = [rules.LABELS[code].lower() for code in codes]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{joined} sales"


def _percent(value: str | None) -> str:
    if value is None:
        return "not available"
    sign = "" if value.startswith("-") or value == "0.00" else "+"
    return f"{sign}{value}%".replace("-", "−")


def kwh(value: str | None) -> str:
    """Million kWh with a sign and thousands separators, exact as computed: "+1,234.567", "−0.002"."""
    if value is None:
        return "not available"
    number = Decimal(value)
    sign = "+" if number > 0 else "−" if number < 0 else ""
    return f"{sign}{format(abs(number), ',f')}"


def _row(code: str, comparison: dict) -> dict:
    return {"code": code, "key": rules.KEYS[code], "label": rules.LABELS[code],
            "role": "analyzed" if code in rules.ANALYZED else "context", **comparison}


def _rows(comparisons: dict) -> tuple[list[dict], list[dict]]:
    return [_row(code, comparisons[code]) for code in rules.ANALYZED], \
        [_row(code, comparisons[code]) for code in rules.CONTEXT]


def _groups(found: dict) -> dict:
    return {**{name: [rules.LABELS[code] for code in found[name]] for name in
               ("up", "down", "little_changed", "unavailable")}, "finding": found["finding"]}


def _contributions(found: dict) -> dict:
    if found["state"] != "computed":
        return found
    return {**found, "rows": [{"code": code, "label": rules.LABELS[code], "change": found["sectors"][code],
                               "role": "analyzed" if code in rules.ANALYZED else "context"} for code in rules.SECTORS]}


def _days_note(days: int, prior_days: int, label: str, prior_label: str) -> str:
    if days == prior_days:
        return f"{label} and {prior_label} both have {days} days; weekdays, holidays and billing cycles are not adjusted."
    return f"{label} has {days} days and {prior_label} {prior_days}; no calendar adjustment is made."


def month_view(row: dict) -> dict:
    sectors, context = _rows(row["comparisons"])
    label, prior_label = month_label(row["month"]), month_label(row["prior"])
    return {"month": row["month"], "label": label, "prior": row["prior"], "prior_label": prior_label,
            "days": row["days"], "prior_days": row["prior_days"], "sectors": sectors, "context": context,
            "divergence": _groups(row["divergence"]), "reconciliation": row["reconciliation"],
            "contributions": _contributions(row["contributions"]),
            "days_note": _days_note(row["days"], row["prior_days"], label, prior_label)}


def period_view(period: dict) -> dict:
    sectors, context = _rows(period["comparisons"])
    label, prior_label = period_label(period["current"]), period_label(period["prior"])
    return {"label": label, "prior_label": prior_label, "months": period["current"], "prior_months": period["prior"],
            "days": period["days"], "prior_days": period["prior_days"], "sectors": sectors, "context": context,
            "divergence": _groups(period["divergence"]), "contributions": _contributions(period["contributions"]),
            "days_note": _days_note(period["days"], period["prior_days"], label, prior_label)}


def _card(kind: str, key: str, view: dict, source: dict) -> dict:
    found = view["divergence"]
    up = [code for code in rules.ANALYZED if rules.LABELS[code] in found["up"]]
    down = [code for code in rules.ANALYZED if rules.LABELS[code] in found["down"]]
    total = next(row for row in view["context"] if row["code"] == rules.TOTAL)
    if total["class"] == "unavailable":
        whole = f"Total retail sales are not available for this comparison ({total['reason']})."
    else:
        whole = (f"Total retail sales changed {_percent(total['percent'])} ({kwh(total['change'])} million kWh) against "
                 f"{view['prior_label']}.")
    unit = "period" if kind == "period" else "month"
    return {
        "type": kind, "id": f"{kind}|{key}", "key": key, "label": view["label"], "prior_label": view["prior_label"],
        "title": f"{view['label']}: {_names(up)} up, {_names(down)} down from {view['prior_label']}",
        "observed": view["sectors"] + view["context"],
        "adds": (f"{whole} That single figure does not show that {_names(down)} were down 1% or more while "
                 f"{_names(up)} were up 1% or more."),
        "interpretation": (f"Against the same {unit} a year earlier, retail sales to these sectors moved in opposite "
                           "directions by at least 1% each. This describes reported retail sales only; it does not say "
                           "why they differ."),
        "others": {"little_changed": found["little_changed"], "unavailable": found["unavailable"]},
        "contributions": view["contributions"], "notes": [view["days_note"]], "disclosures": list(DISCLOSURES),
        "source": source,
    }


def cards(months: list[dict], period: dict, source: dict) -> dict:
    monthly = [_card("month", view["month"], view, source) for view in sorted(months, key=lambda v: v["month"],
                                                                              reverse=True)
               if view["divergence"]["finding"]]
    key = f"{period['months'][0]}..{period['months'][-1]}"
    period_card = _card("period", key, period, source) if period["divergence"]["finding"] else None
    return {"order": ORDER, "monthly": monthly, "period": period_card,
            "total": len(monthly) + (1 if period_card else 0)}

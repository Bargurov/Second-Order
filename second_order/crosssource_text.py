"""Fixed text for the cross-source comparisons (cross-source-text-0.1). Reviewed wording; no figures are written here
except through the verified result, and nothing here states a cause, a weight, a lag or a verdict."""
from calendar import month_name

TEXT_VERSION = "cross-source-text-0.1"
SCOPE = ("Descriptive comparisons across two retained sources: EIA Monthly Energy Review Table 7.6 retail electricity "
         "sales and Federal Reserve G.17 industrial production, set side by side for the same periods. They are not "
         "transmission findings, research evidence, forecasts or recommendations, and nothing here enters research "
         "summaries.")
SIGN_LABELS = {
    "same_sign": "Same sign", "opposite_signs": "Opposite signs",
    "no_direction": "No direction (an exact zero, or G.17 printed 0.0)",
    "not_covered": "Not covered by the retained EIA file", "unavailable": "Unavailable",
    "not_printed": "Not printed in a retained G.17 release",
}
SIGN_NOTE = ("Signs describe only whether each reported change is above or below zero; there is no size threshold, "
             "and they are not the ±1% categories of Electricity by sector. A G.17 rate printed as 0.0 has no direction "
             "because its unrounded value could lie on either side. Growth rates are never subtracted or combined.")
COMMON = (
    "Time alignment does not make these the same measurement: retail electricity purchases are not total electricity "
    "consumption, and an output index is not kilowatthours.",
    "G.17 rates are seasonally adjusted; the EIA retail sales are not. Comparing the same quarter or month of "
    "consecutive years limits seasonal differences but does not remove weather or calendar differences.",
    "The sources are different vintages: each G.17 value is as printed in the release named beside it, and the EIA "
    "file is one retrieval whose edition is not stated. They are not a common historical information set.",
    "Whether the Federal Reserve's output measures draw on EIA data is not stated in the retained material, so the two "
    "sources are not treated as independent: agreement between them is not corroboration.",
    "Observed periods only. They neither validate nor invalidate either series as a general guide to the other, and no "
    "cause is established.",
)
COMPARISONS = {
    "industrial_vs_manufacturing": {
        "title": "Industrial electricity retail sales and manufacturing output",
        "question": ("When retail electricity sales to the industrial class change, did manufacturing output change in "
                     "the same direction over the same period?"),
        "eia_measure": ("EIA Table 7.6: electricity sales to ultimate customers, industrial class (ESICPUS), million kWh, "
                        "not seasonally adjusted; a fourth quarter is the October-December total."),
        "g17_measure": ("G.17 Table 1: Manufacturing (NAICS 31-33), percent change of a seasonally adjusted output "
                        "index, as printed."),
        "differences": (
            "The EIA industrial class is a class of service, not NAICS manufacturing: it includes agriculture and "
            "irrigation from 2003 (Table 7.6 footnote d), and its other members are not stated in the retained "
            "material.",
            "Retail sales leave out electricity generated and used on site. Table 7.6's direct use is one aggregate, not "
            "split by sector; its net change cannot show industrial self-generation, because its parts may offset.",
        ),
        "possibilities": (
            "Industry mix: industries' electricity use per unit of output differs, so the two can diverge when "
            "composition changes.",
            "Weather: cooling and irrigation loads can change electricity purchases without any change in factory output.",
            "On-site generation: more or less self-generation can change purchases for the same use.",
            "Changes among customers in the industrial class outside manufacturing.",
        ),
        "possibilities_note": "Possibilities only: these observations do not establish any of them.",
        "link": {"section": "electricity", "label": "Electricity by sector (EIA Table 7.6)"},
        "link_g17": {"section": "g17", "label": "Industries and revisions (G.17)"},
    },
    "utility_output_and_customers": {
        "title": "Electric utility output and the customer breakdown of electricity retail sales",
        "question": ("When electric utility output changes, how did EIA retail sales change by customer class over the "
                     "same period?"),
        "eia_measure": ("EIA Table 7.6: total retail sales (ESTCPUS) and its four customer classes, million kWh, not "
                        "seasonally adjusted."),
        "g17_measure": ("G.17 Table 1: Utilities / Electric (NAICS 2211), percent change of a seasonally adjusted "
                        "output index, as printed."),
        "differences": (
            "The customer breakdown decomposes EIA total retail sales only. It does not show which customers drove the "
            "change in G.17 utility output, and the two are shown side by side, not reconciled.",
            "Utility output and retail sales measure different things; how far they differ in any period (for example "
            "through losses, wholesale trade or own use) is not measured here.",
        ),
        "possibilities": (),
        "possibilities_note": None,
        "link": {"section": "electricity", "label": "Electricity by sector (EIA Table 7.6)"},
        "link_g17": {"section": "g17", "label": "Industries and revisions (G.17)"},
    },
}


def period_label(period: dict) -> str:
    if period["kind"] == "fourth_quarter":
        return f"Q4 {period['year']} vs Q4 {period['year'] - 1}"
    year, month = int(period["key"][:4]), int(period["key"][5:])
    return f"{month_name[month]} {year} vs {month_name[month]} {year - 1}"

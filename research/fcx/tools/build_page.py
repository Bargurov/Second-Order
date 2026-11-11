"""Write research/fcx/page.json: the FCX company page's texts and tables (company-page-0.2).

The texts are written here, by hand. The Numbers tables are built from tools/key_tables.json, with a change column
wherever a computed change record uses exactly the two figures of the row. Edit this file, then run it; never edit
page.json by hand. The server (second_order/company_research_view.py) checks every text on each read:
- no digits but years: every number is a placeholder that the page fills from its record;
- no causal or forecast phrasing of the page's own (the fuels notes' phrase rule);
- no valuation words.

AI draft, not reviewed by the project owner: every text block carries its kind, and the page stamps the
interpretation.

Run from the repository root: python -I research/fcx/tools/build_page.py
"""
import json
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]


def b(kind: str, text: str, *passages: str, **extra) -> dict:
    """One text block: observation, computed, estimate, company_reason, reading or note."""
    return {"kind": kind, "text": text, **({"passages": list(passages)} if passages else {}), **extra}


SUMMARY = [  # shown: two or three sentences
    b("company_reason", "In the third quarter of 2026 Freeport-McMoRan sold {{r3-cu-sales-q3-2026}} of copper on its "
                        "consolidated basis, against {{r3-cu-sales-q3-2025}} a year earlier; the company names lower "
                        "operating rates at PTFI while the Grasberg Block Cave mine ramps up after the September 2025 mud "
                        "rush.", "r3-p-cu-sales-reason"),
    b("observation", "In the company's revenue bridge for the quarter, the volume lines of the three metals "
                     "({{c-rev-bridge-volume-q3-2026|signed}}) outweighed the price lines "
                     "({{c-rev-bridge-price-q3-2026|signed}}), yet revenue rose on its other lines."),
    b("observation", "In November the board approved a {{nr-bagdad-capex-estimate}} expansion of the Bagdad mine in "
                     "Arizona; its cost, output and timing are company estimates.", "nr-p-board-approval"),
]

SUMMARY_MORE = [  # in a closed fold under the summary
    b("observation", "Freeport-McMoRan mines copper in the United States, Peru and Chile, and Indonesia; copper was "
                     "{{k25-revenue-share-copper-fy2025}} of its consolidated revenues in 2025."),
    b("company_reason", "The largest of the other revenue lines was Atlantic Copper, the Spanish smelter "
                        "({{q3-rev-bridge-atlantic-q3-2026|signed}}), whose copper purchases also raised costs; lower "
                        "export duties added {{q3-rev-bridge-export-duties-q3-2026|signed}}.", "q3-p-cost-drivers"),
    b("company_reason", "Unit net cash costs rose to {{r3-cu-unc-q3-2026}} a pound, from {{r3-cu-unc-q3-2025}}; they "
                        "leave out mud-rush idle costs of {{q3-idle-pd-per-lb-q3-2026}} a pound.", "r3-p-unc-reason"),
    b("observation", "Operating cash flows for the first nine months of 2026 were {{r3-ocf-9m-2026}}, including "
                     "{{r3-cf-insurance-9m-2026}} of insurance proceeds. For the same months of 2025 the 10-Q shows "
                     "{{q3-ocf-9m-2025}} and the release {{r3-ocf-9m-2025}}; neither explains the difference."),
    b("reading", "FCX's share of consolidated net income rose to {{c-common-share-ni-q3-2026}}, from "
                 "{{c-common-share-ni-q3-2025}}: Indonesia, where FCX owns {{r3-ptfi-ownership}}, earned less. The "
                 "company names this beside prices and lower taxes, without saying how much each explains.",
      "q3-p-ni-common-reason"),
]

TILES = [
    {"id": "copper-sales", "label": "Copper sales", "value": "r3-cu-sales-q3-2026", "compare": "r3-cu-sales-q3-2025",
     "compare_label": "A year earlier"},
    {"id": "copper-price", "label": "Realized copper price", "value": "r3-cu-price-q3-2026",
     "compare": "r3-cu-price-q3-2025", "compare_label": "A year earlier"},
    {"id": "unit-costs", "label": "Unit net cash costs", "value": "r3-cu-unc-q3-2026", "compare": "r3-cu-unc-q3-2025",
     "compare_label": "A year earlier", "note_label": "Leaves out idle costs",
     "note": b("note", "Leaves out mud-rush idle costs of {{q3-idle-pd-per-lb-q3-2026}} a pound.")},
    {"id": "ocf", "label": "Operating cash flows", "value": "r3-ocf-9m-2026", "compare": "r3-ocf-9m-2025",
     "compare_label": "A year earlier, in the release", "note_label": "The 10-Q differs for the earlier year",
     "note": b("note", "Includes {{r3-cf-insurance-9m-2026}} of insurance proceeds. The 10-Q shows "
                       "{{q3-ocf-9m-2025}} for the same months of 2025; neither document explains the difference.")},
    {"id": "ocf-less-capex", "label": "Operating cash flow less capex",
     "value": "c-ocf-less-capex-9m-2026", "compare": "c-ocf-less-capex-9m-2025",
     "compare_label": "A year earlier, from the release", "note_label": "On the 10-Q's earlier figure",
     "note": b("note", "On the 10-Q's figure for the earlier year it is {{c-ocf-less-capex-9m-2025-10q}}.")},
    {"id": "net-debt", "label": "Net debt, excluding PTFI project debt",
     "value": "r3-nd-net-debt-ex-2026-09-30", "compare": "r3-net-debt-target",
     "compare_label": "Target range starts at", "note_label": "How the company defines it",
     "note": b("note", "Net debt excludes the debt for PTFI's downstream processing facilities.",
               "q3-p-net-debt-target")},
]

CHANGES = [
    {"id": "price", **b("observation", "The realized copper price rose to {{r3-cu-price-q3-2026}} a pound "
                                       "({{c-yoy-cu-price-q3-2026|signed}})."),
     "detail": [
         b("observation", "The LME averaged {{r3-lme-avg-q3-2026}} a pound and COMEX {{r3-comex-avg-q3-2026}} in the "
                          "quarter, as the company states them.", "r3-p-realized-basis"),
         b("observation", "Some sales are priced one to four months after shipment, so a price move reaches revenue "
                          "over more than one quarter. At the end of September {{r3-provisional-lbs}} were still "
                          "provisionally priced.", "r3-p-provisional"),
     ]},
    {"id": "volume", **b("company_reason", "Copper sales were {{r3-cu-sales-q3-2026}} "
                                           "({{c-yoy-cu-sales-q3-2026|signed}}). Indonesia sold "
                                           "{{r3-id-cu-sales-q3-2026}}, against {{r3-id-cu-sales-q3-2025}}.",
                         "r3-p-cu-sales-reason"),
     "detail": [
         b("observation", "PTFI's mills ran at {{r3-mill-capacity-share-q3-2026}} of capacity in the quarter. "
                          "Production ran ahead of sales at the Indonesian smelters.", "r3-p-prod-vs-sales"),
         b("estimate", "The company's plan: eighty percent of capacity in mid-2027, near full capacity by the end "
                       "of 2027.", "r3-p-ramp-up"),
     ]},
    {"id": "revenue", **b("observation", "Revenue was {{r3-revenues-q3-2026}} ({{c-yoy-revenues-q3-2026|signed}}): "
                                         "in the company's bridge, volumes {{c-rev-bridge-volume-q3-2026|signed}}, "
                                         "prices {{c-rev-bridge-price-q3-2026|signed}}, other lines "
                                         "{{c-rev-bridge-other-lines-q3-2026|signed}}."),
     "detail": [
         b("observation", "Copper alone: prices {{q3-rev-bridge-cu-price-q3-2026|signed}}, volumes "
                          "{{q3-rev-bridge-cu-volume-q3-2026|signed}}. Gold volumes "
                          "{{q3-rev-bridge-au-volume-q3-2026|signed}}."),
         b("company_reason", "The largest other line is Atlantic Copper, the Spanish smelter "
                             "({{q3-rev-bridge-atlantic-q3-2026|signed}}). The company's reason for higher production "
                             "costs starts with its copper purchases, so that revenue came with costs.",
           "q3-p-cost-drivers"),
         b("observation", "Lower export duties added {{q3-rev-bridge-export-duties-q3-2026|signed}}. Duties were charged "
                          "on concentrate exports until the export licence expired in September 2025.",
           "q3-p-export-duty-expiry"),
         b("note", "The full bridge is under Numbers. The grouping into volume, price and other lines is this "
                   "project's; the lines are the company's."),
     ]},
    {"id": "unit-costs", **b("company_reason", "Unit net cash costs rose by {{c-chg-cu-unc-q3-2026}} a pound, to "
                                               "{{r3-cu-unc-q3-2026}} a pound.", "r3-p-unc-reason"),
     "detail": [
         b("observation", "They leave out mud-rush idle facility, recovery and restoration costs: "
                          "{{r3-idle-costs-q3-2026}} in the quarter, or {{q3-idle-pd-per-lb-q3-2026}} a pound.",
           "r3-p-idle-costs"),
         b("reading", "While the ramp-up lasts, read the excluded idle costs beside the unit cost. Adding the two is "
                      "this project's arithmetic, not a company measure."),
     ]},
    {"id": "share", **b("company_reason", "Operating cash flows were {{r3-ocf-q3-2026}} "
                                          "({{c-yoy-ocf-q3-2026|signed}}); FCX's share of consolidated net income rose "
                                          "to {{c-common-share-ni-q3-2026}}, from {{c-common-share-ni-q3-2025}}.",
                        "q3-p-ni-common-reason"),
     "detail": [
         b("observation", "Cash used for working capital rose in the quarter.", "q3-p-wc-quarter"),
         b("reading", "The share of profit moves with the mix: Indonesia, where FCX owns {{r3-ptfi-ownership}}, earned "
                      "less, and the wholly owned U.S. mines earned more. The company names this beside prices and "
                      "lower taxes, without saying how much each explains."),
     ]},
]

READING_GUIDE = [
    b("note", "Quarter, nine-month and annual figures sit in separate columns, and a change is only shown between "
              "periods of the same length."),
    b("note", "Consolidated figures include all of PTFI, Cerro Verde and El Abra, though FCX owns {{r3-ptfi-ownership}}, "
              "{{r3-cerro-verde-ownership}} and {{k25-ownership-el-abra}} of them. Figures attributable to common stock "
              "are FCX shareholders' part, and they are labelled."),
    b("note", "Nine-month operating income and operating cash flows include a one-off insurance settlement of "
              "{{r3-cf-insurance-9m-2026}}. Without it, nine-month operating cash flows would be "
              "{{c-ocf-ex-insurance-9m-2026}}, which is this project's arithmetic."),
]

BUSINESS = [
    {"id": "sells", "title": "What it sells", "open": "yes", "blocks": [
        b("observation", "Revenue in 2025: copper {{k25-revenue-share-copper-fy2025}}, gold "
                         "{{k25-revenue-share-gold-fy2025}}, molybdenum {{k25-revenue-share-molybdenum-fy2025}}."),
        b("observation", "Copper production in 2025: the United States {{k25-prod-alloc-copper-us-fy2025}}, South "
                         "America {{k25-prod-alloc-copper-south-america-fy2025}}, Indonesia "
                         "{{k25-prod-alloc-copper-indonesia-fy2025}}. Indonesia produced "
                         "{{k25-prod-alloc-gold-indonesia-fy2025}} of the gold.", "k25-gold-mostly-grasberg"),
        b("observation", "In the United States FCX is the leading copper supplier.", "k25-us-refined-share"),
    ]},
    {"id": "assets", "title": "Key assets and who owns them", "teaser": "Ownership and how each is reported",
     "assets": [
         {"name": "Grasberg minerals district (PTFI)", "place": "Indonesia",
          "what": "Underground copper and gold mines, with smelting in Indonesia", "record": "r3-ptfi-ownership",
          "reported": "Consolidated in full, with noncontrolling interests"},
         {"name": "Cerro Verde", "place": "Peru", "what": "Copper and molybdenum concentrator",
          "record": "r3-cerro-verde-ownership", "reported": "Consolidated in full, with noncontrolling interests"},
         {"name": "El Abra", "place": "Chile", "what": "Copper", "record": "k25-ownership-el-abra",
          "reported": "Consolidated in full, with noncontrolling interests"},
         {"name": "Morenci", "place": "United States, Arizona", "what": "The largest open-pit copper mine of the group",
          "record": "r3-morenci-interest", "reported": "Only FCX's share is included (proportionate consolidation)"},
         {"name": "Bagdad, Safford, Sierrita, Chino, Tyrone, Miami", "place": "United States",
          "what": "Open-pit copper; Bagdad and Sierrita also molybdenum", "record": None,
          "reported": "Wholly owned, consolidated"},
     ],
     "blocks": [b("observation", "Partly owned mines are consolidated in full, so reported totals include the "
                                 "partners' shares.", "k25-ptfi-consolidation-basis")]},
    {"id": "share", "title": "Consolidated figures against FCX's share", "teaser": "One worked line for copper and one "
                                                                                     "for profit",
     "blocks": [
         b("observation", "Copper sold in the third quarter of 2026: {{r3-cu-sales-q3-2026}} consolidated, less "
                          "{{r3-cu-nci-q3-2026-sales}} for noncontrolling interests, leaves {{r3-cu-net-q3-2026-sales}} "
                          "as FCX's net share ({{c-net-share-cu-sales-q3-2026}})."),
         b("observation", "Net income: {{r3-net-income-q3-2026}} consolidated, {{r3-ni-nci-q3-2026|size}} to "
                          "noncontrolling interests, {{r3-ni-common-is-q3-2026}} to FCX's common stockholders."),
         b("observation", "Since January 2023 PTFI's profit is attributed by equity ownership.", "k25-ptfi-attribution"),
     ]},
    {"id": "mud-rush", "title": "The September 2025 mud rush", "teaser": "What happened and the restart",
     "blocks": [
         b("observation", "The incident at the Grasberg Block Cave mine.", "k25-mud-rush-event"),
         b("observation", "The smelters in Indonesia restarted in the second half of 2026.", "r3-p-smelter"),
         b("estimate", "The company's plan for the ramp-up.", "r3-p-ramp-up"),
         b("observation", "Idle facility costs are charged to the period while operations run below normal.",
           "r3-p-idle-costs"),
     ]},
    {"id": "indonesia", "title": "The Indonesian framework", "teaser": "Mining rights, fiscal terms, export rules",
     "blocks": [
         b("observation", "Mining rights.", "k25-iupk-term"),
         b("observation", "Fiscal terms.", "k25-iupk-fiscal-terms"),
         b("observation", "Export proceeds rule.", "k25-export-proceeds-rule"),
         b("observation", "After 2041, under the 2026 memorandum of understanding.", "r3-p-mou"),
         b("observation", "Tax assessments received in October 2026, with no outcome stated.",
           "q3-p-tax-assessments-2023"),
         b("observation", "Refined gold exports and the export duty, unresolved.", "r3-p-gold-export"),
     ]},
    {"id": "reserves", "title": "Reserves", "teaser": "Copper reserves and the price they assume",
     "blocks": [
         b("observation", "Copper reserves at the end of 2025: {{k25-reserves-copper-consolidated}} consolidated, "
                          "{{k25-reserves-copper-net-equity}} net of noncontrolling interests, at an assumed copper "
                          "price of {{k25-reserves-price-assumption-copper}} a pound."),
         b("observation", "Indonesia's reserves are counted only to the end of its licence.",
           "k25-reserves-indonesia-through-2041"),
         b("reading", "The reserve price is about half the realized price of the third quarter of 2026 "
                      "({{r3-cu-price-q3-2026}} a pound), so the estimate does not rest on today's price level. The 10-K "
                      "does not say how much larger reserves would be at a higher assumed price."),
     ]},
]

MECHANISM_STEPS = [
    {"id": "price", "title": "Copper price to realized price", "link": "stated", "blocks": [
        b("observation", "U.S. sales follow COMEX monthly averages; South America and Indonesia follow the LME.",
          "r3-p-realized-basis", "k25-lme-basis-sa-indonesia"),
        b("observation", "Provisional pricing carries a price move into later quarters.", "r3-p-provisional")]},
    {"id": "volume", "title": "Volume to revenue and unit costs", "link": "stated", "blocks": [
        b("observation", "Grasberg is the swing: at normal rates it produces about {{r3-ptfi-normal-rates}} of copper "
                         "a year.", "k25-ptfi-costs-fixed")]},
    {"id": "credits", "title": "By-products to unit costs", "link": "stated", "blocks": [
        b("observation", "Gold and molybdenum revenue is netted against copper costs.", "r3-p-byproduct-method"),
        b("observation", "Gold sold later moves the unit cost too.", "r3-p-unc-vs-estimate")]},
    {"id": "royalties", "title": "Royalties, duties, profit sharing and taxes", "link": "conditional", "blocks": [
        b("observation", "The Indonesian fiscal terms set royalty and tax rates.", "k25-iupk-fiscal-terms"),
        b("reading", "Several of these rise with price, so less than the full revenue change reaches cash. The "
                     "company gives no bridge.")]},
    {"id": "working-capital", "title": "Working capital", "link": "stated", "blocks": [
        b("observation", "Inventory held at PTFI's smelters defers sales into later periods.", "r3-p-wc-deferral"),
        b("reading", "When that inventory is sold it should return cash; when depends on the smelter ramp-up and on "
                     "the gold export question.")]},
    {"id": "capex", "title": "Capital expenditure", "link": "stated", "blocks": [
        b("estimate", "The 2026 capital expenditure outlook is {{r3-out-capex-fy2026}}, before the Bagdad approval.")]},
    {"id": "nci", "title": "Noncontrolling interests to cash for FCX", "link": "stated", "blocks": [
        b("observation", "Distributions to noncontrolling interests in the first nine months of 2026: "
                         "{{r3-cf-dist-nci-9m-2026|size}}, against {{r3-cf-dist-nci-9m-2025|size}} a year earlier. "
                         "The 10-Q names Cerro Verde for 2026.", "q3-p-nci-distributions"),
        b("note", "PTFI's dividends to FCX itself are internal to the group, so they are not in the consolidated cash "
                  "flow statement. The 10-K gave {{k25-ptfi-dividends-to-fcx-fy2025}} for 2025; the 10-Q gives no "
                  "figure for 2026, so it is unknown here.", "k25-holding-company-dividends-shared"),
        b("observation", "Cash at international operations was {{q3-cash-international-2026-09-30}} at the end of "
                         "September, not split by subsidiary.", "q3-p-cash-international-use")]},
    {"id": "policy", "title": "Financial policy", "link": "stated", "blocks": [
        b("observation", "The policy for shareholder returns.", "r3-p-financial-policy")]},
]

SENSITIVITIES = [
    {"id": "release-copper", "record": "r3-sens-ocf-copper", "measure": "Operating cash flows",
     "period_text": "A copper price change in the fourth quarter of 2026 only", "effect_on": "The year 2026",
     "passages": ["r3-p-sens-copper", "r3-p-sens-conditions"]},
    {"id": "tenk-copper", "record": "k25-sensitivity-ocf-copper-fy2026", "measure": "Operating cash flows",
     "period_text": "A copper price change across all of 2026, as of February", "effect_on": "The year 2026",
     "passages": ["k25-ocf-sensitivity-wording", "k25-ocf-outlook-conditions"]},
    {"id": "release-gold", "record": "r3-sens-ocf-gold", "measure": "Operating cash flows",
     "period_text": "A gold price change in the fourth quarter of 2026 only", "effect_on": "The year 2026",
     "passages": ["r3-p-sens-conditions"]},
    {"id": "release-moly", "record": "r3-sens-ocf-moly", "measure": "Operating cash flows",
     "period_text": "A molybdenum price change in the fourth quarter of 2026 only", "effect_on": "The year 2026",
     "passages": ["r3-p-sens-conditions"]},
    {"id": "tenk-gold", "record": "k25-sensitivity-ocf-gold-fy2026", "measure": "Operating cash flows",
     "period_text": "A gold price change across all of 2026, as of February", "effect_on": "The year 2026",
     "passages": ["k25-ocf-sensitivity-wording-2"]},
    {"id": "tenk-moly", "record": "k25-sensitivity-ocf-moly-fy2026", "measure": "Operating cash flows",
     "period_text": "A molybdenum price change across all of 2026, as of February", "effect_on": "The year 2026",
     "passages": ["k25-ocf-sensitivity-wording-2"]},
    {"id": "tenk-nci", "record": "k25-sensitivity-net-income-nci-copper-fy2026",
     "measure": "Net income attributable to noncontrolling interests",
     "period_text": "A copper price change across all of 2026, as of February", "effect_on": "The year 2026"},
    {"id": "provisional", "record": "r3-provisional-sens", "measure": "Revenues",
     "period_text": "Settlement of the sales still provisionally priced at the end of September 2026",
     "effect_on": "The year 2026", "passages": ["r3-p-provisional"]},
]

SENSITIVITY_NOTE = b("note", "The two copper figures describe different periods of price change, price levels and "
                             "volumes. They are not two estimates of one quantity, and the company does not bridge "
                             "them, so neither is converted into the other.")

BAGDAD = {
    "decided": [
        b("observation", "The board approved the expansion and modernization program for Bagdad, FCX's wholly owned "
                         "copper and molybdenum mine in Arizona.", "nr-p-board-approval", "q3-p-bagdad-approval"),
        b("observation", "Engineering, procurement planning and early works are under way, and the 2026 outlook already "
                         "includes early works.", "nr-p-early-works", "q3-p-bagdad-early-works"),
    ],
    "estimates": [
        {"label": "Capital cost", "record": "nr-bagdad-capex-estimate"},
        {"label": "Copper a year in the long term, more than", "record": "nr-bagdad-cu-total"},
        {"label": "Of which incremental copper a year", "record": "nr-bagdad-cu-increment"},
        {"label": "Molybdenum a year in the long term, more than", "record": "nr-bagdad-mo-total"},
        {"label": "Of which incremental molybdenum a year", "record": "nr-bagdad-mo-increment"},
        {"label": "Construction period", "record": "nr-bagdad-construction-years"},
        {"label": "Lower long-term unit net cash costs", "record": "nr-bagdad-uncc-reduction"},
        {"label": "Copper price supporting break-even economics", "record": "nr-bagdad-breakeven-cu"},
        {"label": "Share of project costs funded in the first year of spending", "record": "nr-bagdad-funding-2027"},
    ],
    "estimate_notes": [
        b("estimate", "Initial production is targeted for mid-2030.", "nr-p-schedule"),
        b("estimate", "The company names cost risk.", "nr-p-cost-risk", "nr-p-aim"),
        b("estimate", "The spending will be added to an updated capital expenditure outlook, as discretionary.",
          "nr-p-discretionary"),
    ],
    "computed": [
        {"label": "Implied funding in the first year of spending", "record": "c-bagdad-funding-2027"},
        {"label": "Implied funding in the second year, low end", "record": "c-bagdad-funding-2028-low"},
        {"label": "Implied funding in the second year, high end", "record": "c-bagdad-funding-2028-high"},
        {"label": "Implied funding in the last two years together, low end", "record": "c-bagdad-funding-2029-2030-low"},
        {"label": "Implied funding in the last two years together, high end",
         "record": "c-bagdad-funding-2029-2030-high"},
        {"label": "Incremental copper against consolidated copper sales in 2025",
         "record": "c-bagdad-cu-increment-share-fy2025"},
        {"label": "Incremental copper against FCX's net copper sales in 2025",
         "record": "c-bagdad-cu-increment-share-net-fy2025"},
        {"label": "Change in the capital estimate since February", "record": "c-bagdad-capex-estimate-change"},
    ],
    "history": [b("observation", "The mine and its fleet.", "nr-p-history", "nr-p-autonomous"),
                b("observation", "Copper produced at Bagdad in 2025: {{k25-bagdad-cu-production-fy2025}}.")],
    "change_columns": ["10-K (2026-02-13)", "Results release (2026-10-27)", "Bagdad release (2026-11-04)",
                       "10-Q (signed 2026-11-06)"],
    "change_rows": [
        {"label": "Capital cost estimate", "ids": ["k25-bagdad-capex-estimate", "r3-bagdad-capex-estimate",
                                                   "nr-bagdad-capex-estimate", "q3-bagdad-capex-estimate"]},
        {"label": "Incremental copper a year, low end of the range", "ids": ["k25-bagdad-cu-increment-low",
                                                                            "r3-bagdad-cu-increment-low", None, None]},
        {"label": "Incremental copper a year, high end of the range", "ids": ["k25-bagdad-cu-increment-high",
                                                                             "r3-bagdad-cu-increment-high", None,
                                                                             None]},
        {"label": "Incremental copper a year, single figure", "ids": [None, None, "nr-bagdad-cu-increment",
                                                                     "q3-bagdad-cu-increment"]},
        {"label": "Incentive copper price", "ids": ["k25-bagdad-incentive-price", "r3-bagdad-incentive-price", None,
                                                    None]},
        {"label": "Copper price supporting break-even economics", "ids": [None, None, "nr-bagdad-breakeven-cu",
                                                                         None]},
    ],
    "change_note": b("note", "Incentive price and break-even are kept in each document's own words; they are not "
                             "treated as one measure. Whether the scope of the capital estimate changed is not stated."),
}

QUESTIONS = [
    {"id": "missing", "title": "Missing from these documents", "items": [
        b("note", "PTFI's dividends to FCX in 2026, and PTFI's own cash, are not disclosed."),
        b("note", "The company gives no bridge for its operating cash flow sensitivity, and no split of costs into "
                  "fixed and variable."),
        b("note", "The other line of the 2025 revenue bridge, {{k25-rev-bridge-other-fy2025|signed}}, is not "
                  "explained further."),
        b("note", "The updated capital expenditure outlook with Bagdad is not published yet."),
        b("note", "The tax assessments in Indonesia carry no stated outcome.", "q3-p-tax-assessments-2023"),
    ]},
    {"id": "follow", "title": "Questions to follow", "items": [
        b("reading", "How much of the full-year operating cash flow outlook rests on gold sales in the fourth quarter, "
                     "and on the gold export question?"),
        b("reading", "When does the inventory at the Indonesian smelters turn back into cash?"),
        b("reading", "What do unit costs look like once Grasberg runs at normal rates?"),
        b("reading", "What does the company mean by break-even economics, against the earlier incentive price?"),
        b("reading", "How do the payout framework and discretionary growth spending share the cash once Bagdad is "
                     "in the outlook?"),
    ]},
    {"id": "unchanged", "title": "Left unchanged on purpose", "items": [
        b("note", "The copper calculator still carries the 10-K's Bagdad figures, and the copper thesis was not "
                  "changed. Updating them is the owner's decision."),
    ]},
]

METHOD = {
    "checks": [
        b("note", "Every figure is a record with its source, page, period, unit and basis. Published figures are "
                  "quoted from the retained documents; computed figures are recomputed with exact decimals."),
        b("note", "Each retained document is checked against its acquisition record on every read. A figure, quote or "
                  "line that rests on a document that is missing or changed is not shown."),
        b("note", "The page's own sentences hold no typed numbers: each number is filled from its record."),
    ],
    "not_doing": [
        b("note", "No valuation, no price for the shares, no projection of the project's own, no advice and no live "
                  "prices."),
    ],
}

# Stage 2, the Scenarios tab (research/fcx/scenarios-spec.md). Each "base" lists exactly the records the calculation
# uses (second_order/company_scenarios.USES); the numbers come from the records and from the computation, never from
# these words.
SCENARIOS = {
    "intro": b("note", "Two separate calculations on the company's assumptions for the fourth quarter of 2026. Change "
                       "an input and see what changes in each. Neither is a projection of this project's, a valuation "
                       "or a reported result, and the two are never added together."),
    "price_volume": {
        "title": "Copper price and volume sold",
        "short": "Price × volume",
        "base": [{"label": "Copper price", "record": "r3-out-cu-price-q4-2026"},
                 {"label": "Copper sold in the quarter (sales, not production)", "record": "r3-out-cu-sales-q4-2026"}],
        "base_value": {"label": "Price × volume at the company's assumptions", "record": "c-q4-cu-sales-value-base"},
        "definition": b("note", "Price × volume: an approximate value of copper sales under these assumptions. It is "
                                "not reported revenue, earnings or cash flow."),
        "method": [
            b("computed", "The change is split in one fixed order: the volume effect is the change in pounds valued at "
                          "the company's price, and the price effect is the change in price on your volume. The two "
                          "always add up to the change; another order would split it differently."),
        ],
        "sources": [
            b("estimate", "The company's copper price for the fourth quarter, {{r3-out-cu-price-q4-2026}} a pound, is "
                          "the price its 2026 outlook assumes.", "r3-p-sens-conditions"),
            b("estimate", "The company's copper sales for the fourth quarter: {{r3-out-cu-sales-q4-2026}}."),
        ],
        "costs": [
            b("company_reason", "The 10-K says a significant portion of PTFI's costs are fixed and its unit costs vary "
                                "with volumes.", "k25-ptfi-costs-fixed"),
            b("note", "These documents give no split of costs into fixed and variable, and no bridge from volume to "
                      "operating cash flows."),
            b("reading", "So a change in volume is not carried to cash flow here. Holding the cost per pound constant "
                         "while volume changes would treat every cost as variable, which the 10-K says is not so at "
                         "PTFI; for the other mines these documents give no split either way.", "k25-ptfi-costs-fixed"),
        ],
    },
    "cash_flow": {
        "title": "The company's published cash flow sensitivity",
        "short": "Cash flow sensitivity",
        "base": [{"label": "Copper price", "record": "r3-out-cu-price-q4-2026"},
                 {"label": "Change in operating cash flows for each step", "record": "r3-sens-ocf-copper"},
                 {"label": "Step in the average copper price", "record": "r3-sens-ocf-copper-step"}],
        "definition": b("estimate", "The company's figure: each {{r3-sens-ocf-copper-step}} a pound change in the average "
                                    "copper price during the fourth quarter of 2026 would change consolidated operating "
                                    "cash flows for the year 2026 by about {{r3-sens-ocf-copper}}, at its current sales "
                                    "volume and cost estimates.", "r3-p-sens-copper", "r3-p-sens-conditions"),
        "linear": b("note", "Multiplying that figure by your price change is this project's linear use of the company's "
                            "approximate figure. The company gives it for each step around "
                            "{{r3-out-cu-price-q4-2026}} a pound and does not say over what range of prices it holds."),
        "held": b("note", "Volumes, costs and the company's other assumptions stay as the company states them; only the "
                          "average copper price in the fourth quarter moves.", "r3-p-sens-conditions"),
        "not_used": [
            b("note", "A change in volume from the first calculation is not added here: the company publishes no figure "
                      "for how cash flows move with volume."),
            b("note", "The 10-K's older sensitivity, for a price change across all of 2026 at its February assumptions, "
                      "is not used: it belongs to another period, price level and volume.", "k25-ocf-sensitivity-wording"),
        ],
        "versus": b("computed", "At the company's volume, a {{r3-sens-ocf-copper-step}} move in price adds "
                                "{{c-q4-copper-revenue-per-10c}} to price × volume for the quarter, while the company's "
                                "figure for operating cash flows is {{r3-sens-ocf-copper}}. They measure different "
                                "things. The company does not split the difference, so this page does not put it down "
                                "to taxes, royalties, a cost or timing."),
    },
}


def numbers() -> dict:
    tables = json.loads((FOLDER / "tools" / "key_tables.json").read_bytes().decode("utf-8"))
    facts = json.loads((FOLDER / "facts.json").read_bytes().decode("utf-8"))
    computed = [r for r in facts["records"] if r["kind"] == "computed" and r["id"].startswith(("c-yoy-", "c-chg-"))]

    def change(a, b_):
        if not a or not b_:
            return None
        found = [r["id"] for r in computed if sorted(r["inputs"].values()) == sorted([a, b_])]
        return found[0] if found else None

    by_title = {t["title"]: t for t in tables}

    def split(title, start, label):
        table = by_title[title]
        rows = []
        for name, ids in table["rows"]:
            pair = ids[start:start + 2]
            if not any(pair):
                continue
            rows.append({"label": name, "ids": [pair[0], pair[1], change(pair[0], pair[1])]})
        return {"title": label, "columns": table["columns"][start:start + 2] + ["Change"], "rows": rows}

    q_bridge = by_title["The company's revenue bridge: quarter and nine months (10-Q)"]
    k_bridge = by_title["The company's revenue bridge: full year (10-K)"]
    difference_q = b("note", "The 10-Q shows {{q3-ocf-quarter-q3-2025}} for the third quarter of 2025; the release shows "
                             "{{r3-ocf-q3-2025}}. Neither document explains the difference.")
    difference_9m = b("note", "The 10-Q shows {{q3-ocf-9m-2025}} for the first nine months of 2025; the release shows "
                              "{{r3-ocf-9m-2025}}. Neither document explains the difference.")

    def with_note(table, row_label, note):
        for row in table["rows"]:
            if row["label"] == row_label:
                row["note"] = note
        return table

    fin_q = with_note(split("Quarter and nine months: financial figures", 0, "Financial figures"), "Operating cash flows",
                      difference_q)
    fin_9 = with_note(split("Quarter and nine months: financial figures", 2, "Financial figures"), "Operating cash flows",
                      difference_9m)
    return {
        "views": [
            {"id": "quarter", "label": "Quarter", "main": fin_q, "more": [
                split("Quarter and nine months: operating figures", 0, "Operating figures"),
                split("Segment operating income", 0, "Segment operating income"),
                {"title": "The company's revenue bridge", "columns": [q_bridge["columns"][0]],
                 "rows": [{"label": name, "ids": [ids[0]]} for name, ids in q_bridge["rows"]]},
            ]},
            {"id": "nine-months", "label": "Nine months", "main": fin_9, "more": [
                split("Quarter and nine months: operating figures", 2, "Operating figures"),
                split("Segment operating income", 2, "Segment operating income"),
                {"title": "The company's revenue bridge", "columns": [q_bridge["columns"][1]],
                 "rows": [{"label": name, "ids": [ids[1]]} for name, ids in q_bridge["rows"]]},
            ]},
            {"id": "year", "label": "Year", "main": split("Full years (10-K): financial figures", 0, "Financial figures"),
             "more": [
                 split("Full years (10-K): operating figures", 0, "Operating figures"),
                 {"title": "The company's revenue bridge", "columns": k_bridge["columns"],
                  "rows": [{"label": name, "ids": ids} for name, ids in k_bridge["rows"]]},
             ]},
        ],
        "dated": [
            {"title": "Cash and debt", "columns": by_title["Balance sheet: cash, debt and equity"]["columns"],
             "rows": [{"label": name, "ids": ids} for name, ids in by_title["Balance sheet: cash, debt and equity"]["rows"]]},
            {"title": "The 2026 outlook in February and in October (company estimates)",
             "columns": ["10-K (February)", "Q3 2026 reports (October)"],
             "rows": [{"label": name, "ids": ids} for name, ids in
                      by_title["The 2026 outlook in February (10-K) and in October (Q3 2026 reports)"]["rows"]]},
        ],
        "difference": [
            b("observation", "The 10-Q shows operating cash flows for the first nine months of 2025 of "
                             "{{q3-ocf-9m-2025}}; the release of October shows {{r3-ocf-9m-2025}}. The gap is "
                             "{{c-ocf-difference-9m-2025|signed}}."),
            b("note", "Neither document mentions or explains the difference. Both figures are "
                      "kept; the tables use the release's, so that each quarter's figures come from one "
                      "document."),
        ],
    }


def page() -> dict:
    return {
        "page_version": "company-page-0.2",
        "company": {"name": "Freeport-McMoRan", "short": "FCX", "kicker": "Company research · Copper producer"},
        "question": "How does the copper price reach Freeport-McMoRan's cash flow, and what held its volumes back in "
                    "2026?",
        "figures_to": "2026-09-30",
        "review": {"author": "AI", "state": "not_reviewed"},
        "summary": SUMMARY,
        "summary_more": SUMMARY_MORE,
        "tiles": TILES,
        "changes": CHANGES,
        "reading_guide": READING_GUIDE,
        "business": BUSINESS,
        "numbers": numbers(),
        "mechanisms": {"steps": MECHANISM_STEPS, "sensitivities": SENSITIVITIES, "sensitivity_note": SENSITIVITY_NOTE,
                       "bagdad": BAGDAD},
        "scenarios": SCENARIOS,
        "questions": QUESTIONS,
        "method": METHOD,
    }


def main() -> None:
    (FOLDER / "page.json").write_bytes((json.dumps(page(), indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print("page.json written")


if __name__ == "__main__":
    main()

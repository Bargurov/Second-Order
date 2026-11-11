// Plain-language economics beside the metals figures. General notes: none names a metal, company or country,
// and none states a price direction, a forecast, a recommendation or a cause.
import { YEARS_LABEL } from "./metals.ts";

export interface Note { id: string; term: string; text: string }

export const NOTES: Note[] = [
  {
    id: "concentration",
    term: "Concentration",
    text: "A country's share is its part of world output. Concentration asks how much of that output the three largest named producers hold together. "
      + "The ranking is among the countries USGS names. USGS reports the rest as one group, “Other countries”, which USGS does not split: that group is never ranked, and it can hold more than a named country does. "
      + "So the three largest named producers are not a complete ranking of the world, and the group's own share is shown beside them in each table. "
      + "When the share is high, a few countries' policies, disruptions or costs weigh on everyone else's supply; when it is low, supply is spread across many places. "
      + "A share here is of the world total as USGS prints it. USGS rounds most world totals (the tables say where), so the shares in one table may add up to more or less than 100.",
  },
  {
    id: "indicators",
    term: "Concentration indicators",
    text: "The largest named country's share (CR1) and the three largest named countries' combined share (CR3) are their printed figures divided by the world total USGS prints. "
      + "The Herfindahl–Hirschman index (HHI) adds up each named country's squared share and multiplies by 10,000, so it runs from near 0 (output spread thinly) to 10,000 (one country holds everything). "
      + "USGS does not split “Other countries”, so the HHI is shown as two bounds: the low end treats that group as spread so thinly that it adds nothing, the high end treats it as one holder. "
      + "Beside every HHI stands its coverage, the named countries' part of the printed world total: the lower the coverage, the wider the bounds. Where the named countries add to more than the printed total, which USGS rounds, the page says so. "
      + "The same measures are taken over US import sources, whose shares USGS prints as percentages of US imports for the years each table states. "
      + "Each indicator is shown on its own; none is combined into a score.",
  },
  {
    id: "stages",
    term: "Mining and refining",
    text: "Mining and refining (or smelting) are different stages, and they are often done in different countries. "
      + "A metal can be mined in many places yet refined in only a few, so concentration can be much higher at one stage than at the other.",
  },
  {
    id: "reserves-stocks",
    term: "Reserves, resources and stocks",
    text: "In USGS's terms, reserves are the part of known deposits that can be extracted economically today. The resources are larger and less certain: they include deposits that may become worth extracting later. "
      + "Metal already mined and held is called stocks. This stage shows no stocks; they come in a later stage, and there is no way to know available stocks precisely.",
  },
  {
    id: "years-of-reserves",
    term: "Years of reserves",
    text: "Years of reserves is reserves divided by 2025 output, shown " + YEARS_LABEL + ". "
      + "Under one year it reads “less than 1 year”. Where a table's unit is in doubt, no figure is made from it, and the table says why. "
      + "It is not a date when anything runs out: reserves change with price, technology and exploration, and output changes too.",
  },
  {
    id: "by-products",
    term: "By-products",
    text: "Some metals are recovered mostly as a by-product of mining or refining another metal, called the host. "
      + "Their supply then follows the host's output more than their own price. Which metals these are is shown later, from sources that state it.",
  },
  {
    id: "printed-codes",
    term: "Printed codes",
    text: "Values are shown exactly as USGS prints them, letters and signs included. "
      + "A country printed as a dash (“—”) is read as zero when countries are ordered and their shares added, and is given no share of its own. "
      + "The codes' key is not retained in this stage, so every other code is shown as printed and not interpreted here.",
  },
  {
    id: "two-sources",
    term: "Two sources",
    text: "USGS and IEA figures are never added or compared: they use different scopes and definitions. "
      + "IEA years after 2025 are its own projections.",
  },
  {
    id: "importance",
    term: "Importance, criticality and supply risk",
    text: "Three different things, not one. Industrial importance is how much of a metal goes into which uses: here, the IEA's energy-technology demand and, where a retained source states them, end uses. "
      + "Strategic criticality is a designation: whether USGS's data file marks the metal as on the 2025 list of critical minerals, a policy judgment about essential uses and supply. "
      + "Supply risk is measured from the figures: how concentrated production and reserves are, and how much US supply relies on imports, and on which sources. "
      + "A metal can matter greatly to industry while its supply is spread widely, or be marked critical while its output is spread; the three are shown apart and never added up.",
  },
  {
    id: "transmission",
    term: "Economic transmission",
    text: "A transmission chain traces how a disruption at one stage could pass to the firms that use a metal and to their customers. The chains are written by the assistant and are not reviewed by the owner. "
      + "Each link carries a label. Measured: a figure on this page, shown with its value or with the reason it is not shown. Stated by a source: a passage quoted from a retained, verified source, with its place, or the reason the quote is withheld. "
      + "Hypothesis: a step neither measured nor stated by a retained source. "
      + "Who is directly or indirectly exposed, who may gain or may lose and through which mechanism, and what could soften the effect are the assistant's reading of the chain, not measurements. "
      + "Each chain ends with what the data shows and what is assumed, kept apart. No chain is a price view or advice.",
  },
  {
    id: "events",
    term: "Events",
    text: "An event is shown only when a retained primary source (an official publication or a filing), dated, states it, quoted with the source's title, publisher and edition and its place; when that source cannot be checked on this read, its quote is withheld. "
      + "Each event carries the date its quote gives, and the page checks that the date is in the quote: an event from a past report reads as past, not as news. "
      + "No news feed, sanctions list or export-control notice is retained in this stage, so the absence of an event here says nothing about whether one happened. "
      + "The structural exposure beside the events (the largest country at each stage, whether one country is largest at several stages, the largest US import source) describes where supply sits, not what has happened.",
  },
];

/** The source and data year of the world production and reserves figures each indicator is computed from. */
const WORLD_2025 = "Source: USGS Mineral Commodity Summaries 2026 data release, 2025.";

/** What each indicator means, one click from where it is shown: its formula, source, data year and coverage limit. */
export const ABOUT = {
  cr1: "Largest named country's share (CR1): its printed figure divided by the world total USGS prints, to one decimal. "
    + `${WORLD_2025} Ranked among the countries USGS names; “Other countries”, which USGS does not split, is never ranked.`,
  cr3: "Three largest named countries' combined share (CR3): their printed figures added and divided by the printed world total. "
    + `${WORLD_2025} Not shown when fewer than three countries are named, or when a named country is printed as a code.`,
  hhi: "HHI: the sum of each named country's squared share, times 10,000 (near 0 when spread thinly, 10,000 for one country). "
    + "Shown as two bounds because the unsplit “Other countries” could be many small holders (low end) or one (high end). "
    + WORLD_2025,
  coverage: "Coverage: the named countries' figures added, as a share of the printed world total. "
    + "The lower it is, the wider the HHI bounds; above 100 the named figures exceed the printed total, which USGS rounds. "
    + WORLD_2025,
  reliance: "US net import reliance: as USGS prints it, net imports as a percentage of apparent consumption. "
    + "A code or a bound is shown exactly as printed and not interpreted. "
    + "Where a chapter prints more than one 2025 figure (one per commodity), the first is shown, named by its commodity, and every one is listed under US imports and reliance. "
    + "Source: USGS Mineral Commodity Summaries 2026 data release, 2025.",
  imports: "US import sources: USGS's percentages of US imports by country, for the years each table states. "
    + "The largest source, the three largest combined and the HHI of sources (its bounds and coverage against 100) are computed as for world output. These are shares of US imports, not of world supply. "
    + "Source: USGS Mineral Commodity Summaries 2026 data release, import sources 2021–24.",
  concentrated: "Largest single-country share, by stage: of the production stages, the one whose largest named country holds the largest share (CR1). "
    + `A stage whose largest country cannot be ranked is left out. ${WORLD_2025}`,
} as const;

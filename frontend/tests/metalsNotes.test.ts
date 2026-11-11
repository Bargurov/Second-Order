// The plain notes beside the metals figures (metalsNotes.ts): general economics, no metal named, no claim made.
import assert from "node:assert/strict";
import { test } from "node:test";
import { YEARS_LABEL } from "../src/metals.ts";
import { ABOUT, NOTES } from "../src/metalsNotes.ts";

// second_order/metals_usgs.py CHAPTER_NAMES, copied (metals.ts exports ids, not names); display_name is str.capitalize().
const CHAPTER_NAMES = [
  "ALUMINUM", "BAUXITE AND ALUMINA", "ANTIMONY", "ARSENIC", "BERYLLIUM", "BISMUTH", "CADMIUM", "CESIUM", "CHROMIUM",
  "COBALT", "COPPER", "GALLIUM", "GERMANIUM", "GOLD", "GRAPHITE (NATURAL)", "INDIUM", "IRON ORE", "LEAD", "LITHIUM",
  "MAGNESIUM METAL", "MANGANESE", "MERCURY", "MOLYBDENUM", "NICKEL", "NIOBIUM (COLUMBIUM)", "PLATINUM-GROUP METALS",
  "RARE EARTHS", "RARE EARTHS (Heavy)", "RHENIUM", "RUBIDIUM", "SCANDIUM", "SELENIUM", "SILICON", "SILVER", "TANTALUM",
  "TELLURIUM", "THALLIUM", "TIN", "TITANIUM AND TITANIUM DIOXIDE", "TITANIUM MINERAL CONCENTRATES", "TUNGSTEN",
  "VANADIUM", "YTTRIUM", "ZINC", "ZIRCONIUM AND HAFNIUM"];
const DISPLAY_NAMES = CHAPTER_NAMES.map((name) => name.charAt(0).toUpperCase() + name.slice(1).toLowerCase());
const text = (id: string) => NOTES.find((note) => note.id === id)!.text;
const escape = (name: string) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// Every word the notes give: each Method note and each indicator's note shown beside the figures.
const everything = () => [...NOTES.map((note) => note.term + " \n " + note.text), ...Object.values(ABOUT)].join(" \n ");

test("the notes come in the stated order", () => {
  assert.deepEqual(NOTES.map((note) => note.id),
    ["concentration", "indicators", "stages", "reserves-stocks", "years-of-reserves", "by-products", "printed-codes",
      "two-sources", "importance", "transmission", "events"]);
  for (const note of NOTES) assert.ok(note.term.length > 0 && note.text.length > 0);
});

test("each note says what it is for", () => {
  assert.match(text("concentration"), /share/);
  assert.match(text("concentration"), /few countries|three/);
  assert.match(text("concentration"), /world total as USGS prints it\. USGS rounds most world totals/);
  assert.match(text("concentration"), /may add up to more or less than 100/);
  // The ranking is among the countries USGS names; "Other countries" is one unsplit group, never ranked.
  assert.match(text("concentration"), /three largest named producers/);
  assert.match(text("concentration"), /among the countries USGS names/);
  assert.match(text("concentration"), /“Other countries”, which USGS does not split/);
  assert.match(text("concentration"), /not a complete ranking of the world/);
  assert.match(text("years-of-reserves"), /less than 1 year/);
  assert.match(text("years-of-reserves"), /unit is in doubt/);
  assert.match(text("stages"), /refin/);
  assert.match(text("stages"), /mine|mining/);
  for (const word of [/reserves/, /resources/, /stocks/]) assert.match(text("reserves-stocks"), word);
  assert.match(text("reserves-stocks"), /later stage/);
  assert.ok(text("reserves-stocks").includes("there is no way to know available stocks precisely"));
  assert.ok(text("years-of-reserves").includes(YEARS_LABEL));
  assert.match(text("years-of-reserves"), /change with price|technology|exploration/);
  assert.match(text("years-of-reserves"), /reserves divided by 2025 output/);
  assert.doesNotMatch(text("years-of-reserves"), /this year/);
  assert.match(text("by-products"), /by-product/);
  assert.match(text("by-products"), /host/);
  assert.match(text("printed-codes"), /as USGS prints them/);
  assert.match(text("printed-codes"), /key is not retained in this stage/);
  // A dash is read as zero for the order only; every other code is shown as printed, never interpreted.
  assert.match(text("printed-codes"), /printed as a dash \(“—”\) is read as zero when countries are ordered/);
  assert.match(text("printed-codes"), /given no share of its own/);
  assert.match(text("printed-codes"), /every other code is shown as printed and not interpreted/);
  assert.match(text("two-sources"), /USGS and IEA figures are never added or compared/);
  // The concentration indicators: formulas, the two HHI bounds and coverage, the import sources, and no score.
  assert.match(text("indicators"), /\(CR1\)/);
  assert.match(text("indicators"), /\(CR3\)/);
  assert.match(text("indicators"), /squared share and multiplies by 10,000/);
  assert.match(text("indicators"), /two bounds: the low end .* the high end treats it as one holder/);
  assert.match(text("indicators"), /coverage, the named countries' part of the printed world total/);
  assert.match(text("indicators"), /more than the printed total/);
  assert.match(text("indicators"), /US import sources/);
  assert.match(text("indicators"), /none is combined into a score/);
  assert.match(text("importance"), /Industrial importance/);
  assert.match(text("importance"), /Strategic criticality is a designation/);
  assert.match(text("importance"), /2025 list of critical minerals/);
  assert.match(text("importance"), /Supply risk is measured/);
  assert.match(text("importance"), /never added up/);
  assert.match(text("transmission"), /written by the assistant and are not reviewed by the owner/);
  for (const label of ["Measured:", "Stated by a source:", "Hypothesis:"]) assert.ok(text("transmission").includes(label));
  assert.match(text("transmission"), /may gain or may lose/);
  assert.match(text("transmission"), /what the data shows and what is assumed/);
  assert.match(text("events"), /only when a retained primary source \(an official publication or a filing\), dated, states it/);
  assert.match(text("events"), /title, publisher and edition/);
  assert.match(text("events"), /absence of an event here says nothing about whether one happened/);
});

test("each indicator's note gives its formula, its source and data year, and its limit", () => {
  assert.deepEqual(Object.keys(ABOUT), ["cr1", "cr3", "hhi", "coverage", "reliance", "imports", "concentrated"]);
  // Every note names its source and its data year, spelled out (no "same source and year").
  const years: Record<string, string> = { cr1: "2025", cr3: "2025", hhi: "2025", coverage: "2025", reliance: "2025",
    imports: "import sources 2021–24", concentrated: "2025" };
  for (const [key, value] of Object.entries(ABOUT)) {
    assert.ok(value.includes(`Source: USGS Mineral Commodity Summaries 2026 data release, ${years[key]}.`), key);
    assert.doesNotMatch(value, /[Ss]ame source/, key);
  }
  assert.match(ABOUT.cr1, /divided by the world total USGS prints/);
  assert.match(ABOUT.cr1, /Mineral Commodity Summaries 2026/);
  assert.match(ABOUT.cr1, /never ranked/);
  assert.match(ABOUT.cr3, /added and divided by the printed world total/);
  assert.match(ABOUT.cr3, /fewer than three countries are named/);
  assert.match(ABOUT.hhi, /squared share, times 10,000/);
  assert.match(ABOUT.hhi, /two bounds/);
  assert.match(ABOUT.coverage, /share of the printed world total/);
  assert.match(ABOUT.coverage, /wider the HHI bounds/);
  assert.match(ABOUT.reliance, /percentage of apparent consumption/);
  assert.match(ABOUT.reliance, /shown exactly as printed and not interpreted/);
  assert.match(ABOUT.imports, /not of world supply/);
  assert.match(ABOUT.concentrated, /largest named country holds the largest share/);
  for (const value of Object.values(ABOUT)) assert.ok(value.length > 40 && !/score/.test(value), value);
});

test("no note or indicator note names a metal (each of the 45 display names, as a whole phrase)", () => {
  assert.equal(DISPLAY_NAMES.length, 45);
  const phrase = (name: string) => new RegExp(`(?<!\\w)${escape(name)}(?!\\w)`, "i");
  // The check fires, including on names that end in a bracket (where a trailing \b would never match).
  assert.match("about Rare earths (heavy) here", phrase("Rare earths (heavy)"));
  assert.match("Graphite (natural).", phrase("Graphite (natural)"));
  assert.match("and niobium (columbium)", phrase("Niobium (columbium)"));
  assert.doesNotMatch("a leading role", phrase("Lead"));
  for (const name of DISPLAY_NAMES) assert.doesNotMatch(everything(), phrase(name), name);
});

test("no note names a country: a withheld file's country names must never reach the page through a note", () => {
  // The browser check scans the whole page for strings only a withheld file holds; a note shown beside the figures
  // (the importance note sits in each metal's Industrial uses) must not carry one. "US" stands for the US figures.
  for (const name of ["United States", "China", "Chile", "Peru", "Congo", "Australia", "Indonesia", "Russia", "Canada"]) {
    assert.doesNotMatch(everything(), new RegExp(`(?<!\\w)${name}(?!\\w)`), name);
  }
  // The check fires on a whole name only.
  assert.match("how much the United States relies", new RegExp(`(?<!\\w)United States(?!\\w)`));
  assert.doesNotMatch("Chileans", new RegExp(`(?<!\\w)Chile(?!\\w)`));
});

test("no note or indicator note states a price direction, a forecast, a recommendation or a cause", () => {
  const own = everything().toLowerCase();
  for (const pattern of [/\b(?:higher|lower|rising|falling) (?:copper )?prices?\b/, /\bprices? (?:will|would|should|could|may)\b/,
    /\b(?:upside|downside|bullish|bearish)\b/, /\b(?:buy|sell)\b/, /\brecommend/, /\bprices? (?:rises?|falls?)\b/,
    /\bforecast/, /\bpredict/, /\bshortages?\b/, /\bwill (?:rise|fall|run out)\b/,
    // The plan's claim words, with their inflections.
    /\bconfirm/, /\bprov(?:e|es|ed|ing|en)\b/, /\bcaus(?:e|es|ed|ing)\b/, /\bbuy/, /\bsell/, /\bsignal/, /\brecommend/,
    /mispric/]) {
    assert.doesNotMatch(own, pattern);
  }
});

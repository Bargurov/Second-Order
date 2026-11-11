// The metals comparison (/api/metals, metals-view-0.5, second_order/metals_view.py): the USGS Mineral Commodity
// Summaries 2026 data-release CSV and the IEA Critical Minerals Dataset 2026 workbook, each verified by the server
// against its acquisition record. The reply is read fail-closed: a part is available only over a verified source, a
// withheld part holds frames only, and every share, rank, concentration and years-of-reserves figure is recomputed
// here exactly (BigInt fractions, copperNumbers.ts) by the server's own rules (metals_usgs.py, metals_iea.py) and
// must equal what the server shows. The risk, uses and research parts are read by metalsStage2.ts, after these.
// Each refusal names its place and rule, never a value.
import type { Loaded } from "./api";
import { div, halfEven, int, lessThan, mul, ofPlain, sum, type Rat } from "./copperNumbers.ts";
import { isRec, need, Refusal } from "./copperTools.ts";
import {
  checkResearch, checkRisk, checkUses, type ResearchPart, type RiskPart, type UsesPart,
} from "./metalsStage2.ts";

export const METALS_VIEW_VERSION = "metals-view-0.5";
/** 0.3: each net import reliance row carries its commodity (metals_usgs._reliance). */
export const USGS_ENGINE = "metals-usgs-0.3";
export const IEA_ENGINE = "metals-iea-0.1";
export const USGS_NUMBER = /^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$/;
export const YEARS_LABEL = "at the 2025 rate; not a depletion date";
/** metals_usgs.YEARS_UNDER_ONE: the years figure when world reserves are under one year of world output. */
export const YEARS_UNDER_ONE = "less than 1";
/** metals_usgs.UNIT_ISSUES: the series whose unit the data file states in conflict with the printed USGS chapter, by
 * id, with the words the series carries. The reader requires exactly these, so a flag can be neither dropped nor added. */
export const UNIT_ISSUES: Readonly<Record<string, string>> = {
  "vanadium/reserves/reserves/metric-tons/2025": "Unit in doubt: the printed USGS chapter (Mineral Commodity "
    + "Summaries 2026, vanadium, page 2) gives these reserves in thousand metric tons, while this data file labels them "
    + "metric tons. The chapter is not a source this page verifies, so the quantities and the years of reserves are "
    + "not shown. The shares do not depend on the unit.",
};
const unitIssue = (id: string): string | null => (Object.hasOwn(UNIT_ISSUES, id) ? UNIT_ISSUES[id] : null);
/** A named country printed exactly as this (trimmed) counts as zero in the order and the sums (metals_usgs.DASH). */
export const DASH = "—";
const REPEATED_TOTAL = "USGS prints more than one world total for this series";
const zeroTotal = (printed: string) => `The world total is printed as “${printed}”, so no share can be computed`;
const SOURCE_IDS = ["usgs-csv-2026", "iea-dataset-2026"];
export const CHAPTER_NAMES = [
  "ALUMINUM", "BAUXITE AND ALUMINA", "ANTIMONY", "ARSENIC", "BERYLLIUM", "BISMUTH", "CADMIUM", "CESIUM", "CHROMIUM",
  "COBALT", "COPPER", "GALLIUM", "GERMANIUM", "GOLD", "GRAPHITE (NATURAL)", "INDIUM", "IRON ORE", "LEAD", "LITHIUM",
  "MAGNESIUM METAL", "MANGANESE", "MERCURY", "MOLYBDENUM", "NICKEL", "NIOBIUM (COLUMBIUM)", "PLATINUM-GROUP METALS",
  "RARE EARTHS", "RARE EARTHS (Heavy)", "RHENIUM", "RUBIDIUM", "SCANDIUM", "SELENIUM", "SILICON", "SILVER", "TANTALUM",
  "TELLURIUM", "THALLIUM", "TIN", "TITANIUM AND TITANIUM DIOXIDE", "TITANIUM MINERAL CONCENTRATES", "TUNGSTEN",
  "VANADIUM", "YTTRIUM", "ZINC", "ZIRCONIUM AND HAFNIUM"];
const chapterId = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
/** metals_usgs.display_name (Python's str.capitalize on these ASCII names). */
export const displayName = (name: string) => name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
export const METAL_IDS: readonly string[] = CHAPTER_NAMES.map(chapterId);
export const MINERAL_IDS = ["copper", "cobalt", "lithium", "nickel", "magnet-rare-earths", "graphite"] as const;
/** metals_iea.MINERALS: each mineral's demand title (its name) and the USGS chapter it maps to, in MINERAL_IDS order. */
const MINERALS: readonly (readonly [string, string])[] = [["Copper", "copper"], ["Cobalt", "cobalt"],
  ["Lithium", "lithium"], ["Nickel", "nickel"], ["Magnet rare earth elements", "rare-earths"],
  ["Graphite (all grades: natural and synthetic)", "graphite-natural"]];
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";
const PLAIN = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
const NORMAL = /^-?(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/;
const SUPPLY_YEARS = ["2025", "2030", "2035", "2040"];
const USGS_FRAME = ["id", "chapter", "name"];
const IEA_FRAME = ["id", "name", "chapter"];

export interface Shown { shown: string | null; reason: string | null }
export interface Cell {
  value: string; number: string | null; notes: string; country?: string; share?: Shown;
  /** The world cell only: whether USGS marks this world total as rounded (its detail ends ": rounded" or ", rounded"). */
  rounded?: boolean;
}
export interface Top { countries: string[]; shown: string | null; reason: string | null }
export interface Series {
  id: string; section: string; commodity: string; statistic: string; detail: string; unit: string; year: string;
  world: Cell | null; other: Cell | null; countries: Cell[]; leader: Top; top3: Top; no_shares: string | null;
  /** UNIT_ISSUES' words for this series, or null: its quantities and unit are then not shown, its shares are. */
  unit_issue: string | null;
}
export interface Years { reserves: string; production: string; shown: string | null; reason: string | null; label: string }
export interface Chapter {
  id: string; chapter: string; name: string; present: boolean; critical: string | null; world_table: boolean;
  data_notes: string[]; series: Series[]; years_of_reserves: Years[];
  imports: { detail: string; years: string; rows: { country: string; value: string; number: string | null }[] }[];
  reliance: { commodity: string; detail: string; year: string; value: string }[];
}
export interface Block {
  stage: string; countries: { country: string; values: Record<string, string>; shares: Record<string, string> }[];
  rest: { values: Record<string, string>; shares: Record<string, string> } | null; total_label: string | null;
  total: Record<string, string>; top3_published: Record<string, string>;
}
export interface Mineral {
  id: string; name: string; chapter: string; scope_note: string | null;
  demand: { rows: { label: string; values: Record<string, string> }[]; energy_share: Record<string, string> };
  supply: Block[]; notes: { demand: string[]; supply: string[] };
}
interface Part { engine: string; state: "available" | "withheld"; problem: string | null }
export interface MetalsView {
  view_version: string; provider_called: false; deep: string[];
  sources: { id: string; state: string; [key: string]: unknown }[];
  usgs: Part & { chapters: Chapter[] | { id: string; chapter: string; name: string }[] };
  iea: Part & { minerals: Mineral[] | { id: string; name: string; chapter: string }[] };
  risk: RiskPart; uses: UsesPart; research: ResearchPart;
}

export const rec = (value: unknown, where: string): Record<string, unknown> => {
  need(isRec(value), where, "is not an object");
  return value as Record<string, unknown>;
};
export const list = (value: unknown, where: string): unknown[] => {
  need(Array.isArray(value), where, "is not a list");
  return value as unknown[];
};
export const text = (value: unknown, where: string): string => {
  need(typeof value === "string", where, "is not text");
  return value as string;
};
export const reasoned = (value: unknown, where: string): string => {
  need(typeof value === "string" && value !== "", where, "needs a reason");
  return value as string;
};
export const sameKeys = (value: Record<string, unknown>, keys: string[], where: string) =>
  need(Object.keys(value).length === keys.length && keys.every((key) => key in value), where,
    `must hold exactly ${keys.join(", ")}`);
export const rat = (value: unknown, where: string): Rat => {
  const out = ofPlain(value);
  need(out !== null, where, "is not a plain decimal");
  return out as Rat;
};
/** part / whole x 100 to one decimal, ROUND_HALF_EVEN, trailing zero kept, never grouped (the server's _percent). */
export const percent = (part: Rat, whole: Rat): string => halfEven(mul(div(part, whole), int(100)), 1).replace(/,/g, "");
const positive = (value: Rat) => value.n > 0n;

/** A printed USGS value: its number is non-null exactly when it matches the grammar, and then lacks its commas. */
function checkCell(value: unknown, where: string): Record<string, unknown> {
  const cell = rec(value, where);
  const printed = text(cell.value, `${where}.value`).trim();
  const expected = USGS_NUMBER.test(printed) ? printed.replace(/,/g, "") : null;
  need(cell.number === expected, `${where}.number`, "is not what the printed value gives");
  return cell;
}

function checkShown(item: unknown, where: string, expected: string | null) {
  const shown = rec(item, where);
  if (expected === null) {
    need(shown.shown === null, `${where}.shown`, "must be withheld");
    reasoned(shown.reason, `${where}.reason`);
  } else {
    need(shown.shown === expected, `${where}.shown`, "does not follow its numbers");
    need(shown.reason === null, `${where}.reason`, "must be empty when a value is shown");
  }
}

/** A named country's size for the order (metals_usgs._size): its number, zero when printed exactly as a dash, or null
 * when printed any other way (W, NA, XX, a range, a bound or a word), so the order is unknown. */
export const sizeOf = (cell: Record<string, unknown>, where: string): Rat | null =>
  cell.number !== null ? rat(cell.number, where) : (cell.value as string).trim() === DASH ? int(0) : null;

function checkTop(top: unknown, where: string, count: number, countries: Record<string, unknown>[], world: Rat | null) {
  const item = rec(top, where);
  const named = countries.map((cell) => ({ name: cell.country as string, value: sizeOf(cell, `${where}.number`) }));
  const ok = world !== null && named.every((cell) => cell.value !== null) && named.length >= count;
  if (!ok) {
    need(list(item.countries, `${where}.countries`).length === 0, `${where}.countries`, "must be empty when withheld");
    checkShown(item, where, null);
    return;
  }
  const ranked = named.map((cell) => ({ name: cell.name, value: cell.value as Rat }))
    .sort((a, b) => {
      const order = a.value.n * b.value.d - b.value.n * a.value.d;
      return order !== 0n ? (order > 0n ? -1 : 1) : a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    }).slice(0, count);
  const names = list(item.countries, `${where}.countries`);
  need(names.length === count && names.every((name, index) => name === ranked[index].name), `${where}.countries`,
    "do not follow (-number, name)");
  checkShown(item, where, percent(sum(ranked.map((cell) => cell.value)), world as Rat));
}

/** What a years entry needs of a series it names: its world total and the fields its pair must share. */
interface Checked {
  world: Rat | null; withheld: boolean; issue: string | null;
  commodity: string; statistic: string; detail: string; unit: string; year: string;
}

function checkSeries(value: unknown, where: string, chapterName: string): Checked & { id: string } {
  const series = rec(value, where);
  const id = text(series.id, `${where}.id`);
  const [commodity, statistic, detail, unit, year] = (["commodity", "statistic", "detail", "unit", "year"] as const)
    .map((key) => text(series[key], `${where}.${key}`));
  // metals_usgs._series: the id is the chapter, statistic, detail, unit and year ids joined by "/", so a years entry
  // that names a series by id names exactly these fields.
  need(id === [chapterId(chapterName), chapterId(statistic), chapterId(detail), chapterId(unit), year].join("/"),
    `${where}.id`, "is not made from the series' chapter, statistic, detail, unit and year");
  need(series.unit_issue === unitIssue(id), `${where}.unit_issue`, "is not the fixed unit issue for this series");
  const world = series.world === null ? null : checkCell(series.world, `${where}.world`);
  const other = series.other === null ? null : checkCell(series.other, `${where}.other`);
  const countries = list(series.countries, `${where}.countries`).map((cell, index) =>
    checkCell(cell, `${where}.countries[${index}]`));
  if (world !== null) need(typeof world.rounded === "boolean", `${where}.world.rounded`, "is not true or false");
  const total = world !== null && world.number !== null && positive(rat(world.number, `${where}.world.number`))
    ? rat(world.number, `${where}.world.number`) : null;
  // The reply shows one world cell, so a repeated world total cannot be seen here: a series the server withheld is
  // read as withheld (every value null, one reason), but one it did not withhold must pass the reader's own test.
  const possible = total !== null && (countries.length > 0 || other !== null);
  if (series.no_shares === null) need(possible, `${where}.no_shares`, "must be given when no share can be computed");
  else reasoned(series.no_shares, `${where}.no_shares`);
  if (world !== null && world.number !== null && total === null && (countries.length > 0 || other !== null)) {
    // A world total printed as zero has its own reason (or a repeated total's, which this reply cannot show).
    need(series.no_shares === zeroTotal(world.value as string) || series.no_shares === REPEATED_TOTAL,
      `${where}.no_shares`, "is not the reason for a world total printed as zero");
  }
  const usable = possible && series.no_shares === null;
  const checkOne = (cell: Record<string, unknown>, place: string) => {
    const expected = usable && cell.number !== null ? percent(rat(cell.number, place), total as Rat) : null;
    checkShown(cell.share, `${place}.share`, expected);
    if (!usable) {
      need(rec(cell.share, `${place}.share`).reason === series.no_shares, `${place}.share.reason`,
        "must be the series' reason");
    }
  };
  countries.forEach((cell, index) => {
    need(typeof cell.country === "string", `${where}.countries[${index}].country`, "is not text");
    checkOne(cell, `${where}.countries[${index}]`);
  });
  if (other !== null) checkOne(other, `${where}.other`);
  checkTop(series.leader, `${where}.leader`, 1, countries, usable ? total : null);
  checkTop(series.top3, `${where}.top3`, 3, countries, usable ? total : null);
  if (!usable) {
    for (const name of ["leader", "top3"]) {
      need(rec(series[name], `${where}.${name}`).reason === series.no_shares, `${where}.${name}.reason`,
        "must be the series' reason");
    }
  }
  return { id, withheld: series.no_shares !== null, issue: unitIssue(id), commodity, statistic, detail, unit, year,
    world: world !== null && world.number !== null ? rat(world.number, `${where}.world.number`) : null };
}

/** metals_usgs._qualifier: the detail without `word`, commas and colons, spaces collapsed, lowercased. */
const qualifier = (base: string, word: string) =>
  base.replace(new RegExp(word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), "").replace(/[,:]/g, "")
    .split(/\s+/).filter(Boolean).join(" ").toLowerCase();

/** A years entry pairs a 2025 Reserves series with the 2025 mine Production series of the same commodity, unit and
 * stage (metals_usgs._years_of_reserves); any other pair is refused, whatever its division gives. */
function checkPair(reserves: Checked, production: Checked, place: string) {
  need(reserves.statistic === "Reserves" && production.statistic === "Production", place,
    "does not pair a reserves series with a production series");
  need(reserves.year === "2025" && production.year === "2025", place, "does not pair two 2025 series");
  need(reserves.commodity === production.commodity, place, "pairs series of different commodities");
  need(reserves.unit === production.unit, place, "pairs series in different units");
  need(production.detail.toLowerCase().includes("mine production")
    && qualifier(production.detail, "mine production") === qualifier(reserves.detail, "reserves"), place,
    "pairs series of different stages");
}

function checkUsgs(chapters: unknown[]) {
  need(chapters.length === METAL_IDS.length && chapters.every((c, i) => isRec(c) && c.id === METAL_IDS[i]),
    "usgs.chapters", "the chapter ids are not the 45, in order");
  chapters.forEach((value, index) => {
    const chapter = rec(value, `usgs.chapters[${index}]`);
    const where = `usgs.${chapter.id}`;
    need(chapter.chapter === CHAPTER_NAMES[index], `${where}.chapter`, "is not the chapter's name");
    const found = new Map<string, Checked>();
    list(chapter.series, `${where}.series`).forEach((series, at) => {
      const out = checkSeries(series, `${where}.series[${at}]`, CHAPTER_NAMES[index]);
      need(!found.has(out.id), `${where}.series[${at}].id`, "is repeated");
      found.set(out.id, out);
    });
    list(chapter.years_of_reserves, `${where}.years_of_reserves`).forEach((item, at) => {
      const place = `${where}.years_of_reserves[${at}]`;
      const years = rec(item, place);
      const reserves = found.get(years.reserves as string), production = found.get(years.production as string);
      need(reserves !== undefined && production !== undefined, place, "names a series the chapter does not hold");
      checkPair(reserves as Checked, production as Checked, place);
      need(years.label === YEARS_LABEL, `${place}.label`, "is not the fixed label");
      const [r, p] = [reserves as Checked, production as Checked];
      const valid = r.world !== null && p.world !== null && positive(r.world) && positive(p.world);
      // A repeated world total is invisible here, so a withheld series may leave its years withheld too.
      const barred = r.withheld || p.withheld;
      // With both world totals usable, the first unit issue (the reserves', then the production's) withholds the
      // figure with its words; otherwise any size is shown, a ratio under one year as "less than 1".
      const issue = r.issue !== null ? `Reserves: ${r.issue}` : p.issue !== null ? `Production: ${p.issue}` : null;
      if (valid && !(barred && years.shown === null)) {
        if (issue !== null) {
          checkShown(years, place, null);
          need(years.reason === issue, `${place}.reason`, "is not the series' unit issue");
        } else {
          const ratio = div(r.world as Rat, p.world as Rat);
          checkShown(years, place, lessThan(ratio, int(1)) ? YEARS_UNDER_ONE : halfEven(ratio, 0).replace(/,/g, ""));
        }
      } else checkShown(years, place, null);
    });
    list(chapter.imports, `${where}.imports`).forEach((group, at) => {
      list(rec(group, `${where}.imports[${at}]`).rows, `${where}.imports[${at}].rows`).forEach((cell, row) =>
        checkCell(cell, `${where}.imports[${at}].rows[${row}]`));
    });
  });
}

function plain(value: unknown, where: string, normal = false) {
  need(typeof value === "string" && PLAIN.test(value), where, "is not a plain decimal");
  if (normal) need(NORMAL.test(value as string), where, "is not normalised");
}
export function plains(map: unknown, years: string[] | null, where: string, normal = false): Record<string, unknown> {
  const values = rec(map, where);
  if (years !== null) {
    need(Object.keys(values).length === years.length && years.every((year) => year in values), where,
      "does not hold exactly the expected years");
  }
  for (const [key, item] of Object.entries(values)) plain(item, `${where}.${key}`, normal);
  return values;
}

function checkIea(minerals: unknown[]) {
  need(minerals.length === MINERAL_IDS.length && minerals.every((m, i) => isRec(m) && m.id === MINERAL_IDS[i]),
    "iea.minerals", "the mineral ids are not the six, in order");
  minerals.forEach((value, index) => {
    const mineral = rec(value, "iea.mineral");
    const where = `iea.${mineral.id}`;
    // The page joins an IEA mineral to its USGS chapter by this field, so it must be the fixed mapping.
    need(mineral.chapter === MINERALS[index][1], `${where}.chapter`, "is not the mineral's fixed USGS chapter");
    const demand = rec(mineral.demand, `${where}.demand`);
    list(demand.rows, `${where}.demand.rows`).forEach((row, at) =>
      plains(rec(row, `${where}.demand.rows[${at}]`).values, null, `${where}.demand.rows[${at}].values`));
    plains(demand.energy_share, null, `${where}.demand.energy_share`, true);
    list(mineral.supply, `${where}.supply`).forEach((item, at) => {
      const place = `${where}.supply[${at}]`;
      const block = rec(item, place);
      const total = plains(block.total, SUPPLY_YEARS, `${place}.total`);
      plains(block.top3_published, SUPPLY_YEARS, `${place}.top3_published`, true);
      const lines = list(block.countries, `${place}.countries`).map((c) => rec(c, `${place}.countries`));
      if (block.rest !== null) lines.push(rec(block.rest, `${place}.rest`));
      lines.forEach((entry, line) => {
        const at2 = `${place}.line[${line}]`;
        const values = plains(entry.values, SUPPLY_YEARS, `${at2}.values`);
        const shares = rec(entry.shares, `${at2}.shares`);
        for (const year of SUPPLY_YEARS) {
          const whole = rat(total[year], `${place}.total.${year}`);
          need(positive(whole), `${place}.total.${year}`, "must be positive");
          need(shares[year] === percent(rat(values[year], `${at2}.values.${year}`), whole), `${at2}.shares.${year}`,
            "does not follow its numbers");
        }
      });
    });
  });
}

function checkPart(view: Record<string, unknown>, key: "usgs" | "iea", index: number) {
  const part = rec(view[key], key);
  const frames = key === "usgs" ? "chapters" : "minerals";
  need(part.engine === (key === "usgs" ? USGS_ENGINE : IEA_ENGINE), `${key}.engine`, "is not the expected engine");
  const source = rec(list(view.sources, "sources")[index], `sources[${index}]`);
  need(source.id === SOURCE_IDS[index], `sources[${index}].id`, `expected ${SOURCE_IDS[index]}`);
  const items = list(part[frames], `${key}.${frames}`);
  if (part.state === "available") {
    need(source.state === "verified", `${key}.state`, "is available over a source that did not verify");
    need(part.problem === null, `${key}.problem`, "must be empty when available");
    if (key === "usgs") checkUsgs(items);
    else checkIea(items);
  } else {
    need(part.state === "withheld", `${key}.state`, "is neither available nor withheld");
    reasoned(part.problem, `${key}.problem`);
    const ids: readonly string[] = key === "usgs" ? METAL_IDS : MINERAL_IDS;
    need(items.length === ids.length && items.every((item, i) => isRec(item) && item.id === ids[i]), `${key}.${frames}`,
      "the withheld frames are not the expected ids, in order");
    items.forEach((item, i) => {
      const where = `${key}.${frames}[${i}]`;
      const frame = rec(item, where);
      sameKeys(frame, key === "usgs" ? USGS_FRAME : IEA_FRAME, `${key}.${frames}`);
      // A frame's words are this code's constants: the chapter's display name and name, or the demand title and the
      // mapped USGS chapter.
      const [name, chapter] = key === "usgs" ? [displayName(CHAPTER_NAMES[i]), CHAPTER_NAMES[i]] : MINERALS[i];
      need(frame.name === name, `${where}.name`, "is not the frame's fixed name");
      need(frame.chapter === chapter, `${where}.chapter`, "is not the frame's fixed chapter");
    });
  }
}

/**
 * The 2025 Reserves series shown beside a 2025 production series: the one the server pairs with it by the
 * years-of-reserves rule (each pair has its years entry, the same pairing metals_usgs uses), else the chapter's only
 * 2025 Reserves series (`paired` false: the page names it by its printed detail), else null.
 */
export function reservesFor(chapter: Chapter, production: Series): { series: Series; paired: boolean } | null {
  const series = Array.isArray(chapter.series) ? chapter.series : [];
  const years = Array.isArray(chapter.years_of_reserves) ? chapter.years_of_reserves : [];
  const pair = years.find((item) => item.production === production.id);
  const paired = pair === undefined ? undefined : series.find((item) => item.id === pair.reserves);
  if (paired !== undefined) return { series: paired, paired: true };
  const reserves = series.filter((item) => item.statistic === "Reserves" && item.year === "2025");
  return reserves.length === 1 ? { series: reserves[0], paired: false } : null;
}

/** The first rule the reply breaks as "place: rule", or null when it reads. Never includes a value. */
export function metalsRefusal(body: unknown): string | null {
  try {
    const view = rec(body, "reply");
    need(view.view_version === METALS_VIEW_VERSION, "view_version", `expected ${METALS_VIEW_VERSION}`);
    need(view.provider_called === false, "provider_called", "a read never calls a provider");
    need(list(view.sources, "sources").length === 2, "sources", "expected the USGS and IEA sources");
    checkPart(view, "usgs", 0);
    checkPart(view, "iea", 1);
    checkRisk(view);
    checkUses(view);
    checkResearch(view);
    return null;
  } catch (error) {
    if (error instanceof Refusal) return error.message;
    throw error;
  }
}

export async function fetchMetals(signal: AbortSignal): Promise<Loaded<MetalsView>> {
  let response: Response;
  try {
    response = await fetch("/api/metals", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRec(body) && typeof body.detail === "string" ? body.detail : `Unexpected response (${response.status}).`;
    return { state: response.status === 503 ? "not-prepared" : "error", message };
  }
  const refusal = metalsRefusal(body);
  return refusal === null ? { state: "ready", data: body as MetalsView }
    : { state: "error", message: `The reply could not be read by this page (${refusal}).` };
}

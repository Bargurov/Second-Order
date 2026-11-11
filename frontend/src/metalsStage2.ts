// The three parts metals-view-0.3 adds to /api/metals (and 0.4 keeps) (second_order/metals_view.py): `risk`, the concentration and
// supply-chain indicators (metals_risk.py, metals-risk-0.1); `uses`, the IEA's energy-technology demand by mineral and
// technology (metals_iea_uses.py, metals-iea-uses-0.1); and `research`, the assistant-written notes with their links
// resolved (metals_research.py, metals-research-0.3: each event dated as its quote dates it). metalsRefusal (metals.ts) calls the checks here once the USGS and
// IEA parts have passed, so each figure is recomputed from parts already read: every indicator from the series cells
// and import rows, exactly (BigInt fractions); every IEA share from its numbers; every measured link resolved again
// from the reply in the server's own words; every cited passage's fields held to its state. A withheld part holds
// frames only. Each refusal names its place and rule, never a value.
//
// metals.ts imports this module and this module imports metals.ts, so nothing here may use a value imported from
// metals.ts at module level (only inside functions): either module can then be loaded first.
import { add, div, halfEven, int, lessThan, mul, sub, sum, type Rat } from "./copperNumbers.ts";
import { isRec, need, refuse, sameList } from "./copperTools.ts";
import {
  CHAPTER_NAMES, displayName, list, METAL_IDS, percent, plains, rat, reasoned, rec, sameKeys, sizeOf, text, USGS_NUMBER,
  YEARS_UNDER_ONE, type Chapter, type Series, type Top, type Years,
} from "./metals.ts";

export const RISK_ENGINE = "metals-risk-0.1";
export const USES_ENGINE = "metals-iea-uses-0.1";
export const RESEARCH_ENGINE = "metals-research-0.3";
/** metals_research.WRITTEN_BY: carried by every research part, available or withheld. */
export const WRITTEN_BY = "Written by the assistant from the figures on this page and retained sources; not reviewed by "
  + "the owner.";
/** metals_research.RESEARCH_PROBLEM: the one reason the research part is withheld. */
export const RESEARCH_PROBLEM = "The research notes are not in the shape this version reads";
/** metals_view.THESIS_UNAVAILABLE: every cited passage's problem when the copper thesis cannot be read. */
export const THESIS_UNAVAILABLE = "The copper thesis cannot be read, so its passages are not shown";
export const NO_RESERVES = "No matching 2025 reserves series";
export const NO_PAIR = "No years figure for this pair";
export const NO_RELIANCE = "USGS prints no 2025 net import reliance for this metal";
const RARE = "Rare earth elements as the IEA lists them, not all rare earths";
const PGM = "The IEA counts iridium apart from the other PGMs";
const HAFNIUM_ZIRCONIUM = "The IEA counts each element apart";
/** metals_iea_uses.MAPPING, in its order: an IEA name, the USGS chapter it maps to and its scope note. */
export const USES_MAPPING: readonly (readonly [string, string, string | null])[] = [
  ["Cadmium", "cadmium", null], ["Chromium", "chromium", null], ["Copper", "copper", null], ["Cobalt", "cobalt", null],
  ["Gallium", "gallium", null], ["Germanium", "germanium", null],
  ["Battery-grade graphite", "graphite-natural", "Battery grade, natural and synthetic; USGS counts natural graphite"],
  ["Hafnium", "zirconium-and-hafnium", HAFNIUM_ZIRCONIUM], ["Zirconium", "zirconium-and-hafnium", HAFNIUM_ZIRCONIUM],
  ["Indium", "indium", null],
  ["Iridium", "platinum-group-metals", PGM], ["PGMs (other than iridum)", "platinum-group-metals", PGM],
  ["Lead", "lead", null], ["Lithium", "lithium", "lithium content"],
  ["Magnesium", "magnesium-metal", "The IEA counts magnesium; USGS's chapter is magnesium metal"],
  ["Manganese", "manganese", null], ["Molybdenum", "molybdenum", null], ["Nickel", "nickel", null],
  ["Niobium", "niobium-columbium", null], ["Selenium", "selenium", null], ["Silicon", "silicon", null],
  ["Silver", "silver", null], ["Tantalum", "tantalum", null], ["Tellurium", "tellurium", null], ["Tin", "tin", null],
  ["Titanium", "titanium-and-titanium-dioxide", "The IEA counts titanium; USGS has two titanium chapters"],
  ["Tungsten", "tungsten", null], ["Vanadium", "vanadium", null], ["Zinc", "zinc", null], ["Arsenic", "arsenic", null],
  ["Neodymium", "rare-earths", RARE], ["Dysprosium", "rare-earths", RARE], ["Praseodymium", "rare-earths", RARE],
  ["Terbium", "rare-earths", RARE], ["Lanthanum", "rare-earths", RARE], ["Total rare earth elements", "rare-earths", RARE],
  ["Yttrium", "yttrium", null]];
const MAPPED = new Map(USES_MAPPING.map(([name, chapter, note]) => [name, { chapter, note }]));
/** metals_iea._demand_keys: the 2025 value, then each scenario's forecast years. */
const DEMAND_KEYS = ["2025", ...["cps", "steps", "hd"].flatMap((scenario) =>
  ["2030", "2035", "2040", "2045", "2050"].map((year) => `${scenario}-${year}`))];
/** metals_risk.stage_of: an export series (Python's `\bexport`) is no stage; then `\bmine\b` (Python's word characters
 * are Unicode letters, digits and "_"), else refin|smelt. */
const EXPORT = /(?<![\p{L}\p{N}_])export/iu;
const MINING = /(?<![\p{L}\p{N}_])mine(?![\p{L}\p{N}_])/iu;
const REFINING = /refin|smelt/iu;
const STAGE_NAMES = ["mining", "refining"] as const;
const OTHER = "Other countries";
const REF_STAGES = ["mining", "refining", "reserves"];
const FIGURES = ["leader", "top3", "hhi", "years"];
const DIRECTIONS = ["may gain", "may lose"];
/** thesis_view.passages' states, and "unavailable" when the thesis cannot be read (metals_view._research). */
const PASSAGE_STATES = ["verified", "changed", "missing", "not_found", "unavailable"];
const PASSAGE = /^copper:([a-z0-9]+(?:-[a-z0-9]+)*)$/;
/** An event may also cite a passage of the FCX research (metals_research.EVENT_PASSAGE); a stated link may not. */
const EVENT_PASSAGE = /^(copper|fcx):([a-z0-9]+(?:-[a-z0-9]+)*)$/;
/** metals_view.FCX_UNAVAILABLE: the fixed reason an fcx passage is unavailable. */
const FCX_UNAVAILABLE = "The FCX research cannot be read on this machine";
/** The source fields a cited passage carries beside its source id (thesis_view.PASSAGE_SOURCE_SHOWN). */
const SOURCE_NAMED = ["title", "publisher", "edition", "edition_date"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** metals_research.YEAR and the date's length: an event's `when` is 4 to 40 characters with a four-digit year. */
const YEAR = /(?<![\p{L}\p{N}_])(?:19|20)\d\d(?![\p{L}\p{N}_])/u;
const CHAIN_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const PASSAGE_LISTS = ["uses", "substitution", "recycling"];
const INDICATOR_KEYS = ["named_share", "over_total", "hhi_low", "hhi_high", "named", "reason"];
const IMPORT_KEYS = ["detail", "years", "leader", "top3", "hhi_low", "hhi_high", "named_share", "reason"];
const CHAIN_KEYS = ["id", "title", "disruption", "links", "direct", "indirect", "gains_losses", "mitigants", "learned",
  "assumed"];
const LINK_KEYS: Readonly<Record<string, string[]>> = { measured: ["text", "kind", "ref", "shown", "unavailable"],
  stated: ["text", "kind", "passage", "evidence", "unavailable"], hypothesis: ["text", "kind"] };

/** A series' concentration (metals_risk._bounds), or every figure null with the series' reason. */
export interface Indicators {
  named_share: string | null; over_total: boolean | null; hhi_low: string | null; hhi_high: string | null;
  named: number | null; reason: string | null;
}
export interface Stage { series: string; detail: string; stage: "mining" | "refining" | "other"; leader: Top; top3: Top }
export interface Alternative { country: string; reserves: string; production: string }
export interface ReservesOnly { country: string; reserves: string }
export interface ImportGroup {
  detail: string; years: string; leader: { country: string; value: string } | null; top3: string | null;
  hhi_low: string | null; hhi_high: string | null; named_share: string | null; reason: string | null;
}
export interface RiskChapter {
  id: string; series: Record<string, Indicators>; stages: Stage[]; missing_stages: ("mining" | "refining")[];
  leaders_differ: boolean | null; most_concentrated: string | null; alternatives: Alternative[] | null;
  reserves_only: ReservesOnly[] | null;
  /** reliance: the chapter's first 2025 net import reliance row (ruling R10), named by its commodity as printed. */
  us: { reliance: { commodity: string; detail: string; value: string } | null; imports: ImportGroup[];
    secondary: { detail: string; unit: string; value: string }[] };
}
export interface Technology { label: string; values: Record<string, string>; share_2025: string | null }
export interface UseEntry {
  name: string; chapter: string; scope_note: string | null; total: Record<string, string>;
  technologies: Technology[] | null;
}
/** A cited passage (thesis_view.passages): its source id and that source's title, publisher, edition and edition date
 * (all null only when the thesis cannot be read), its quote where verified, and its place. */
export interface Evidence {
  id: string; source: string | null; title: string | null; publisher: string | null; edition: string | null;
  edition_date: string | null; quote: string | null; where: string | null;
  state: "verified" | "changed" | "missing" | "not_found" | "unavailable"; problem: string | null;
}
export interface CitedPassage { passage: string; evidence: Evidence }
type UsgsRef = { stage: "mining" | "refining" | "reserves"; figure: "leader" | "top3" | "hhi" | "years" }
  | { reliance: "2025" };
export type Ref = UsgsRef | { iea: string; technology: string };
export interface MeasuredLink { text: string; kind: "measured"; ref: Ref; shown: string | null; unavailable: string | null }
export interface StatedLink {
  text: string; kind: "stated"; passage: string; evidence: Evidence; unavailable: string | null;
}
export interface HypothesisLink { text: string; kind: "hypothesis" }
export type Link = MeasuredLink | StatedLink | HypothesisLink;
export interface Chain {
  id: string; title: string; disruption: string; links: Link[]; direct: string[]; indirect: string[];
  gains_losses: { who: string; direction: "may gain" | "may lose"; mechanism: string }[]; mitigants: string[];
  learned: string; assumed: string;
}
export interface ResearchMetal {
  thesis: "copper" | null; uses: CitedPassage[]; substitution: CitedPassage[]; recycling: CitedPassage[];
  /** Each event with `when`, the date its quote gives ("2025", "September 2025"): what happened then, not news now. */
  events: (CitedPassage & { kind: string; when: string })[]; chains: Chain[];
}
interface PartState { engine: string; state: "available" | "withheld"; problem: string | null }
export interface RiskPart extends PartState { chapters: RiskChapter[] | { id: string; chapter: string; name: string }[] }
export interface UsesPart extends PartState { entries: UseEntry[] | { name: string; chapter: string }[] }
export interface ResearchPart extends PartState { written_by: string; metals: Record<string, ResearchMetal> }

/** metals_risk.stage_of: the supply-chain stage a production series' detail names. */
export function stageOf(detail: string): Stage["stage"] {
  if (EXPORT.test(detail)) return "other";
  if (MINING.test(detail)) return "mining";
  return REFINING.test(detail) ? "refining" : "other";
}

const filled = (value: unknown, where: string): string => {
  need(typeof value === "string" && value !== "", where, "is not non-empty text");
  return value as string;
};
/** Two JSON values are the same, key order aside. */
function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((item, at) => same(item, b[at]));
  if (isRec(a)) {
    return isRec(b) && Object.keys(a).length === Object.keys(b).length
      && Object.keys(a).every((key) => Object.hasOwn(b, key) && same(a[key], b[key]));
  }
  return a === b;
}
/** Larger first, then by name (the server's sort key (-size, name)). */
const bySize = (a: { size: Rat; name: string }, b: { size: Rat; name: string }) =>
  lessThan(b.size, a.size) ? -1 : lessThan(a.size, b.size) ? 1 : a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
/** A whole number as metals_usgs._show(value, 0) writes it, never grouped. */
const whole = (value: Rat) => halfEven(value, 0).replace(/,/g, "");
/** Python's f"{n:,}" on a whole-number string. */
const grouped = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** metals_risk._bounds: named sizes against a whole, exactly; the HHI's low end spreads any unnamed rest so thin it adds
 * nothing, its high end gives the rest to one holder. */
function bounds(sizes: Rat[], world: Rat) {
  const named = sum(sizes);
  const low = mul(sum(sizes.map((size) => mul(div(size, world), div(size, world)))), int(10000));
  const rest = sub(int(1), div(named, world));
  const spare = lessThan(rest, int(0)) ? int(0) : rest;
  return { named_share: percent(named, world), over_total: lessThan(world, named), hhi_low: whole(low),
    hhi_high: whole(add(low, mul(mul(spare, spare), int(10000)))), named: sizes.filter((size) => size.n > 0n).length };
}

function checkIndicators(value: unknown, series: Series, where: string) {
  const item = rec(value, where);
  sameKeys(item, INDICATOR_KEYS, where);
  // A named country printed as a dash counts as zero; any other non-number withholds the figures.
  const sizes = series.countries.map((cell) => sizeOf(cell as unknown as Record<string, unknown>, `${where}.named`));
  if (series.no_shares === null && sizes.every((size) => size !== null)) {
    const expected = bounds(sizes as Rat[], rat(series.world?.number, `${where}.named_share`));
    for (const [key, shown] of Object.entries(expected)) {
      need(item[key] === shown, `${where}.${key}`, "does not follow the series' numbers");
    }
    need(item.reason === null, `${where}.reason`, "must be empty when the figures are shown");
  } else {
    for (const key of INDICATOR_KEYS.slice(0, -1)) need(item[key] === null, `${where}.${key}`, "must be withheld");
    need(item.reason === (series.no_shares ?? series.top3.reason), `${where}.reason`, "is not the series' reason");
  }
}

function checkStages(entry: Record<string, unknown>, produced: Series[], where: string) {
  const stages = list(entry.stages, `${where}.stages`);
  need(stages.length === produced.length, `${where}.stages`, "are not one per 2025 production series");
  stages.forEach((value, at) => {
    const place = `${where}.stages[${at}]`;
    const stage = rec(value, place);
    const series = produced[at];
    sameKeys(stage, ["series", "detail", "stage", "leader", "top3"], place);
    need(stage.series === series.id, `${place}.series`, "is not the chapter's 2025 production series, in order");
    need(stage.detail === series.detail, `${place}.detail`, "is not the series' detail");
    need(stage.stage === stageOf(series.detail), `${place}.stage`, "is not the stage its detail names");
    need(same(stage.leader, series.leader), `${place}.leader`, "is not the series' leader");
    need(same(stage.top3, series.top3), `${place}.top3`, "is not the series' top three");
  });
  const tags = produced.map((series) => stageOf(series.detail));
  need(sameList(list(entry.missing_stages, `${where}.missing_stages`), STAGE_NAMES.filter((name) => !tags.includes(name))),
    `${where}.missing_stages`, "are not the stages no 2025 production series has");
  const first = (name: string) => produced.find((series, at) => tags[at] === name && series.leader.shown !== null);
  const [mining, refining] = [first("mining"), first("refining")];
  need(entry.leaders_differ === (mining === undefined || refining === undefined ? null
    : mining.leader.countries[0] !== refining.leader.countries[0]), `${where}.leaders_differ`,
  "does not follow the first mining and refining leaders");
  let top: string | null = null, share: Rat | null = null;
  for (const series of produced) {
    if (series.leader.shown === null) continue;
    const value = rat(series.leader.shown, `${where}.most_concentrated`);
    if (share === null || lessThan(share, value)) [top, share] = [series.id, value];
  }
  need(entry.most_concentrated === top, `${where}.most_concentrated`,
    "is not the stage with the largest leader share, the first on a tie");
}

/** metals_risk._alternatives: in the first years pair whose two series have shares, the countries whose shown reserves
 * share exceeds their shown production share, and those with reserves but no production row. */
function alternativesOf(chapter: Chapter, where: string): [Alternative[] | null, ReservesOnly[] | null] {
  for (const pair of chapter.years_of_reserves) {
    const reserves = chapter.series.find((series) => series.id === pair.reserves) as Series;
    const production = chapter.series.find((series) => series.id === pair.production) as Series;
    if (reserves.no_shares !== null || production.no_shares !== null) continue;
    const made = new Map(production.countries.map((cell) => [cell.country as string, cell.share?.shown ?? null]));
    const better: Alternative[] = [], only: ReservesOnly[] = [];
    for (const cell of reserves.countries) {
      const shown = cell.share?.shown ?? null, country = cell.country as string;
      if (shown === null) continue;
      const other = made.get(country);
      if (other === undefined) only.push({ country, reserves: shown });
      else if (other !== null && lessThan(rat(other, where), rat(shown, where))) {
        better.push({ country, reserves: shown, production: other });
      }
    }
    const order = (a: ReservesOnly, b: ReservesOnly) =>
      bySize({ size: rat(a.reserves, where), name: a.country }, { size: rat(b.reserves, where), name: b.country });
    return [better.sort(order), only.sort(order)];
  }
  return [null, null];
}

/** metals_risk._import_group: shares of US imports (percent of the whole, so against 100), from the printed rows. */
function importGroup(value: unknown, where: string): Record<string, unknown> {
  const group = rec(value, where);
  const rows = list(group.rows, `${where}.rows`).map((row, at) => rec(row, `${where}.rows[${at}]`));
  rows.forEach((row, at) => text(row.country, `${where}.rows[${at}].country`));
  const named = rows.filter((row) => row.country !== OTHER);
  const entry = { detail: text(group.detail, `${where}.detail`), years: text(group.years, `${where}.years`),
    leader: null, top3: null, hhi_low: null, hhi_high: null, named_share: null, reason: null };
  const sizes = named.map((row) => sizeOf(row, `${where}.rows`));
  const unknown = sizes.indexOf(null);
  if (unknown >= 0) return { ...entry, reason: `A named source is printed as “${named[unknown].value as string}”` };
  const { named_share, hhi_low, hhi_high } = bounds(sizes as Rat[], int(100));
  const ranked = named.map((row, at) => ({ size: sizes[at] as Rat, name: row.country as string, row })).sort(bySize);
  return { ...entry, named_share, hhi_low, hhi_high,
    leader: ranked.length > 0 ? { country: ranked[0].name, value: ranked[0].row.value } : null,
    top3: ranked.length >= 3 ? halfEven(sum(ranked.slice(0, 3).map((item) => item.size)), 1).replace(/,/g, "") : null };
}

function checkUs(value: unknown, chapter: Chapter, where: string) {
  const us = rec(value, where);
  sameKeys(us, ["reliance", "imports", "secondary"], where);
  const source = `usgs.${chapter.id}`;
  const rows = list(chapter.reliance, `${source}.reliance`).map((row, at) => rec(row, `${source}.reliance[${at}]`));
  const first = rows.find((row) => row.year === "2025");
  const reliance = first === undefined ? null : { commodity: text(first.commodity, `${source}.reliance`),
    detail: text(first.detail, `${source}.reliance`), value: text(first.value, `${source}.reliance`) };
  need(same(us.reliance, reliance), `${where}.reliance`,
    "is not the chapter's first 2025 net import reliance, with its commodity");
  const groups = list(chapter.imports, `${source}.imports`);
  const imports = list(us.imports, `${where}.imports`);
  need(imports.length === groups.length, `${where}.imports`, "are not one per import group of the chapter");
  imports.forEach((item, at) => {
    const place = `${where}.imports[${at}]`;
    const group = rec(item, place);
    sameKeys(group, IMPORT_KEYS, place);
    const expected = importGroup(groups[at], `${source}.imports[${at}]`);
    for (const key of IMPORT_KEYS) need(same(group[key], expected[key]), `${place}.${key}`, "does not follow the import rows");
  });
  // The secondary-production rows come from Salient Statistics rows the reply does not carry: only their shape is read.
  list(us.secondary, `${where}.secondary`).forEach((item, at) => {
    const place = `${where}.secondary[${at}]`;
    const row = rec(item, place);
    sameKeys(row, ["detail", "unit", "value"], place);
    for (const key of ["detail", "unit", "value"]) text(row[key], `${place}.${key}`);
  });
}

function checkRiskChapter(value: unknown, chapter: Chapter, where: string) {
  const entry = rec(value, where);
  sameKeys(entry, ["id", "series", "stages", "missing_stages", "leaders_differ", "most_concentrated", "alternatives",
    "reserves_only", "us"], where);
  const indicated = chapter.series.flatMap((series, at) =>
    series.year === "2025" && ["Production", "Reserves"].includes(series.statistic) ? [{ series, at }] : []);
  const held = rec(entry.series, `${where}.series`);
  need(sameList(Object.keys(held), indicated.map((item) => item.series.id)), `${where}.series`,
    "is not the chapter's 2025 production and reserves series, in order");
  for (const { series, at } of indicated) checkIndicators(held[series.id], series, `${where}.series[${at}]`);
  checkStages(entry, chapter.series.filter((series) => series.statistic === "Production" && series.year === "2025"), where);
  const [alternatives, only] = alternativesOf(chapter, `${where}.alternatives`);
  need(same(entry.alternatives, alternatives), `${where}.alternatives`, "do not follow the paired series' shares");
  need(same(entry.reserves_only, only), `${where}.reserves_only`, "do not follow the paired series' shares");
  checkUs(entry.us, chapter, `${where}.us`);
}

function checkFrames(items: unknown[], where: string, frames: Record<string, string>[]) {
  need(items.length === frames.length, where, "the withheld frames are not the expected ones, in order");
  items.forEach((item, at) => {
    const place = `${where}[${at}]`;
    const frame = rec(item, place);
    const keys = Object.keys(frames[at]);
    sameKeys(frame, keys, place);
    for (const key of keys) need(frame[key] === frames[at][key], `${place}.${key}`, `is not the frame's fixed ${key}`);
  });
}

/** The risk part: available exactly when the USGS part is (it is built from it), else its 45 frames with its problem. */
export function checkRisk(view: Record<string, unknown>) {
  const usgs = rec(view.usgs, "usgs"), part = rec(view.risk, "risk");
  sameKeys(part, ["engine", "state", "problem", "chapters"], "risk");
  need(part.engine === RISK_ENGINE, "risk.engine", "is not the expected engine");
  need(part.state === usgs.state, "risk.state", "must be available exactly when the USGS part is");
  const items = list(part.chapters, "risk.chapters");
  if (part.state === "available") {
    need(part.problem === null, "risk.problem", "must be empty when available");
    need(items.length === METAL_IDS.length && items.every((item, at) => isRec(item) && item.id === METAL_IDS[at]),
      "risk.chapters", "the chapter ids are not the 45, in order");
    const chapters = usgs.chapters as Chapter[];
    items.forEach((item, at) => checkRiskChapter(item, chapters[at], `risk.${METAL_IDS[at]}`));
  } else {
    need(part.problem === usgs.problem, "risk.problem", "is not the USGS part's problem");
    checkFrames(items, "risk.chapters", CHAPTER_NAMES.map((name, at) =>
      ({ id: METAL_IDS[at], chapter: name, name: displayName(name) })));
  }
}

function checkUse(value: unknown, where: string, seen: Set<string>) {
  const entry = rec(value, where);
  sameKeys(entry, ["name", "chapter", "scope_note", "total", "technologies"], where);
  const name = text(entry.name, `${where}.name`);
  const mapped = MAPPED.get(name);
  need(mapped !== undefined, `${where}.name`, "is not a name the fixed mapping holds");
  need(!seen.has(name), `${where}.name`, "is repeated");
  seen.add(name);
  need(entry.chapter === mapped?.chapter, `${where}.chapter`, "is not the name's fixed USGS chapter");
  need(entry.scope_note === mapped?.note, `${where}.scope_note`, "is not the name's fixed scope note");
  const total = plains(entry.total, DEMAND_KEYS, `${where}.total`, true);
  if (entry.technologies === null) return;
  // The server divides by sheet 3.1's own total row, which the reply does not carry; it reads technologies only when that
  // row equals this sheet-3.2 total on every key (else it withholds the uses part), so each share divides by this total.
  const base = rat(total["2025"], `${where}.total.2025`);
  list(entry.technologies, `${where}.technologies`).forEach((item, at) => {
    const place = `${where}.technologies[${at}]`;
    const technology = rec(item, place);
    sameKeys(technology, ["label", "values", "share_2025"], place);
    filled(technology.label, `${place}.label`);
    const values = plains(technology.values, DEMAND_KEYS, `${place}.values`, true);
    const part = rat(values["2025"], `${place}.values.2025`);
    // metals_iea._share keeps Decimal's sign: a negative share that rounds to zero reads "-0.0".
    const share = base.n > 0n ? percent(part, base) : null;
    const expected = share === "0.0" && part.n < 0n ? "-0.0" : share;
    need(technology.share_2025 === expected, `${place}.share_2025`, "does not follow its numbers");
  });
}

/** The uses part: available only over the verified IEA workbook, else one frame per mapped name with its problem. */
export function checkUses(view: Record<string, unknown>) {
  const part = rec(view.uses, "uses"), iea = rec(view.iea, "iea");
  const source = rec(list(view.sources, "sources")[1], "sources[1]");
  sameKeys(part, ["engine", "state", "problem", "entries"], "uses");
  need(part.engine === USES_ENGINE, "uses.engine", "is not the expected engine");
  const items = list(part.entries, "uses.entries");
  if (part.state === "available") {
    need(source.state === "verified", "uses.state", "is available over a source that did not verify");
    need(part.problem === null, "uses.problem", "must be empty when available");
    const seen = new Set<string>();
    items.forEach((item, at) => checkUse(item, `uses.entries[${at}]`, seen));
  } else {
    need(part.state === "withheld", "uses.state", "is neither available nor withheld");
    reasoned(part.problem, "uses.problem");
    // Over a workbook that did not verify, both IEA parts give the source's own problem.
    if (source.state !== "verified") need(part.problem === iea.problem, "uses.problem", "is not the IEA part's problem");
    checkFrames(items, "uses.entries", USES_MAPPING.map(([name, chapter]) => ({ name, chapter })));
  }
}

// ---------------------------------------------------------------- research links, resolved again from the reply

type Resolved = [string | null, string | null];
interface Resolver {
  usgs: { chapters: Map<string, Chapter>; risk: Map<string, RiskChapter> } | null; usgsProblem: string | null;
  uses: UseEntry[] | null; usesProblem: string | null;
}

/** metals_research._withheld. */
const withheld = (part: string, problem: string | null) => `The ${part} part is withheld${problem ? `: ${problem}` : ""}`;

/** metals_research._order: "Chile 23.0%" or "48.7% (Chile, Congo (Kinshasa), Peru)", or why it is withheld. */
function orderFigure(top: Top, figure: string): Resolved {
  if (top.shown === null) return [null, top.reason];
  return [figure === "leader" ? `${top.countries[0]} ${top.shown}%` : `${top.shown}% (${top.countries.join(", ")})`, null];
}

/** metals_research._hhi: "2,890–3,050", one number when the bounds are equal. */
function hhiFigure(item: Indicators): Resolved {
  if (item.hhi_low === null || item.hhi_high === null) return [null, item.reason];
  const [low, high] = [grouped(item.hhi_low), grouped(item.hhi_high)];
  return [low === high ? low : `${low}–${high}`, null];
}

function yearsFigure(pair: Years | null): Resolved {
  if (pair === null) return [null, NO_PAIR];
  if (pair.shown === null) return [null, pair.reason];
  return [`${pair.shown} ${pair.shown === "1" || pair.shown === YEARS_UNDER_ONE ? "year" : "years"}`, null];
}

/** Ruling R1 (metals_research._reserves): the reserves series of the first years pair whose production is the first
 * mining stage, else the chapter's only 2025 Reserves series (with no pair), else none. The page's snapshot shows the
 * same series, so a reserves link and the snapshot always name one table. */
export function reservesOf(chapter: Chapter, entry: RiskChapter): [Series | null, Years | null] {
  const mining = entry.stages.find((stage) => stage.stage === "mining");
  const pair = mining === undefined ? undefined : chapter.years_of_reserves.find((item) => item.production === mining.series);
  if (pair !== undefined) return [chapter.series.find((series) => series.id === pair.reserves) as Series, pair];
  const found = chapter.series.filter((series) => series.statistic === "Reserves" && series.year === "2025");
  return found.length === 1 ? [found[0], null] : [null, null];
}

function usgsFigure(ref: UsgsRef, chapter: Chapter, entry: RiskChapter): Resolved {
  if ("reliance" in ref) {
    const reliance = entry.us.reliance;
    if (reliance === null) return [null, NO_RELIANCE];
    return [USGS_NUMBER.test(reliance.value.trim()) ? `${reliance.value}%` : reliance.value, null];
  }
  let top: { leader: Top; top3: Top }, id: string;
  if (ref.stage === "reserves") {
    const [series, pair] = reservesOf(chapter, entry);
    if (series === null) return [null, NO_RESERVES];
    if (ref.figure === "years") return yearsFigure(pair);
    [top, id] = [series, series.id];
  } else {
    const stage = entry.stages.find((item) => item.stage === ref.stage);
    if (stage === undefined) return [null, `USGS prints no 2025 production series at the ${ref.stage} stage for this metal`];
    [top, id] = [stage, stage.series];
  }
  return ref.figure === "hhi" ? hhiFigure(entry.series[id]) : orderFigure(top[ref.figure as "leader" | "top3"], ref.figure);
}

function ieaFigure(ref: { iea: string; technology: string }, metal: string, uses: UseEntry[]): Resolved {
  const found = uses.find((item) => item.name === ref.iea && item.chapter === metal);
  if (found !== undefined && found.technologies === null) {
    return [null, `The IEA's table gives no technology split for ${ref.iea}`];
  }
  const technology = (found?.technologies ?? []).find((item) => item.label === ref.technology);
  if (technology === undefined) return [null, `The IEA lists no ${ref.technology} use for ${ref.iea} in this table`];
  if (technology.share_2025 === null) {
    return [null, `The IEA's 2025 energy-technology total for ${ref.iea} is not positive, so no share is computed`];
  }
  return [`${technology.share_2025}% of 2025 energy-technology demand (${technology.values["2025"]} kt of ${
    (found as UseEntry).total["2025"]} kt)`, null];
}

function measured(ref: Ref, metal: string, resolver: Resolver): Resolved {
  if ("iea" in ref) {
    return resolver.uses === null ? [null, withheld("IEA", resolver.usesProblem)] : ieaFigure(ref, metal, resolver.uses);
  }
  if (resolver.usgs === null) return [null, withheld("USGS", resolver.usgsProblem)];
  return usgsFigure(ref, resolver.usgs.chapters.get(metal) as Chapter, resolver.usgs.risk.get(metal) as RiskChapter);
}

function checkRef(value: unknown, metal: string, where: string): Ref {
  const ref = rec(value, where);
  const keys = Object.keys(ref).sort().join(",");
  if (keys === "figure,stage") {
    need(REF_STAGES.includes(ref.stage as string), `${where}.stage`, "is not mining, refining or reserves");
    need(FIGURES.includes(ref.figure as string), `${where}.figure`, "is not leader, top3, hhi or years");
    need(ref.figure !== "years" || ref.stage === "reserves", `${where}.figure`, "years is a figure of the reserves stage only");
  } else if (keys === "reliance") {
    need(ref.reliance === "2025", `${where}.reliance`, 'is not "2025"');
  } else if (keys === "iea,technology") {
    need(typeof ref.iea === "string" && MAPPED.get(ref.iea)?.chapter === metal, `${where}.iea`,
      "is not an IEA name the fixed mapping gives to this metal");
    filled(ref.technology, `${where}.technology`);
  } else refuse(where, "is not {stage, figure}, {reliance} or {iea, technology}");
  return ref as unknown as Ref;
}

/** A cited passage's evidence (thesis_view.passages): text where verified, its quote withheld and a problem otherwise,
 * its source named (title, publisher, edition, edition date) unless the thesis cannot be read, and the same fields
 * wherever the same passage is cited. */
function checkEvidence(value: unknown, where: string, id: string, seen: Map<string, Record<string, unknown>>,
  ref: string, unavailable: string) {
  const evidence = rec(value, where);
  sameKeys(evidence, ["id", "source", ...SOURCE_NAMED, "quote", "where", "state", "problem"], where);
  need(evidence.id === id, `${where}.id`, "is not the cited passage's id");
  need(PASSAGE_STATES.includes(evidence.state as string), `${where}.state`, "is not a passage state");
  if (evidence.state === "verified") {
    for (const key of ["source", ...SOURCE_NAMED, "quote", "where"]) {
      need(typeof evidence[key] === "string" && evidence[key] !== "", `${where}.${key}`, "must be text when verified");
    }
    need(evidence.problem === null, `${where}.problem`, "must be empty when verified");
  } else {
    need(evidence.quote === null, `${where}.quote`, "must be withheld when the passage is not verified");
    if (evidence.state === "unavailable") {
      // The copper thesis could not be read, so neither its source nor its place is known.
      for (const key of ["source", ...SOURCE_NAMED, "where"]) {
        need(evidence[key] === null, `${where}.${key}`, "must be empty when unavailable");
      }
      need(evidence.problem === unavailable, `${where}.problem`, "is not the fixed reason the passage cannot be read");
    } else {
      for (const key of ["source", ...SOURCE_NAMED, "where"]) filled(evidence[key], `${where}.${key}`);
      reasoned(evidence.problem, `${where}.problem`);
    }
  }
  need(evidence.edition_date === null || DAY.test(evidence.edition_date as string), `${where}.edition_date`,
    "is not a YYYY-MM-DD date");
  const prior = seen.get(ref);  // Keyed by the full reference: copper:a and fcx:a are two passages.
  if (prior === undefined) seen.set(ref, evidence);
  else need(same(prior, evidence), where, "differs from the same passage cited elsewhere");
  return evidence;
}

function checkCited(item: Record<string, unknown>, where: string, seen: Map<string, Record<string, unknown>>,
  event = false) {
  const ref = text(item.passage, `${where}.passage`);
  const match = (event ? EVENT_PASSAGE : PASSAGE).exec(ref);
  need(match !== null, `${where}.passage`, event ? 'is not "copper:<passage id>" or "fcx:<passage id>"'
    : 'is not "copper:<passage id>"');
  const [, ...parts] = match as RegExpExecArray;
  const id = parts[parts.length - 1], fcx = ref.startsWith("fcx:");
  return checkEvidence(item.evidence, `${where}.evidence`, id, seen, ref, fcx ? FCX_UNAVAILABLE : THESIS_UNAVAILABLE);
}

interface Context { resolver: Resolver; seen: Map<string, Record<string, unknown>>; chains: Set<string> }

function checkLink(value: unknown, metal: string, where: string, context: Context) {
  const link = rec(value, where);
  need(typeof link.kind === "string" && Object.hasOwn(LINK_KEYS, link.kind), `${where}.kind`,
    "is not measured, stated or hypothesis");
  sameKeys(link, LINK_KEYS[link.kind as string], where);
  filled(link.text, `${where}.text`);
  if (link.kind === "measured") {
    const [shown, unavailable] = measured(checkRef(link.ref, metal, `${where}.ref`), metal, context.resolver);
    need(link.shown === shown, `${where}.shown`, "is not the figure its ref resolves to");
    need(link.unavailable === unavailable, `${where}.unavailable`, "is not the reason its ref resolves to");
  } else if (link.kind === "stated") {
    const evidence = checkCited(link, where, context.seen);
    need(link.unavailable === (evidence.state === "verified" ? null : evidence.problem), `${where}.unavailable`,
      "does not follow its passage's state");
  }
}

function filledList(value: unknown, where: string) {
  const items = list(value, where);
  need(items.length > 0, where, "is empty");
  return items;
}

function checkChain(value: unknown, metal: string, where: string, context: Context) {
  const chain = rec(value, where);
  sameKeys(chain, CHAIN_KEYS, where);
  const id = text(chain.id, `${where}.id`);
  need(CHAIN_ID.test(id), `${where}.id`, "is not a lower-case id of letters, digits and single hyphens");
  need(!context.chains.has(id), `${where}.id`, "is repeated");
  context.chains.add(id);
  for (const name of ["title", "disruption", "learned", "assumed"]) filled(chain[name], `${where}.${name}`);
  filledList(chain.links, `${where}.links`).forEach((link, at) => checkLink(link, metal, `${where}.links[${at}]`, context));
  for (const name of ["direct", "indirect", "mitigants"]) {
    filledList(chain[name], `${where}.${name}`).forEach((item, at) => filled(item, `${where}.${name}[${at}]`));
  }
  filledList(chain.gains_losses, `${where}.gains_losses`).forEach((value, at) => {
    const place = `${where}.gains_losses[${at}]`;
    const item = rec(value, place);
    sameKeys(item, ["who", "direction", "mechanism"], place);
    filled(item.who, `${place}.who`);
    need(DIRECTIONS.includes(item.direction as string), `${place}.direction`, "is not may gain or may lose");
    filled(item.mechanism, `${place}.mechanism`);
  });
}

function checkResearchMetal(value: unknown, metal: string, where: string, context: Context) {
  const entry = rec(value, where);
  sameKeys(entry, ["thesis", ...PASSAGE_LISTS, "events", "chains"], where);
  need(entry.thesis === null || entry.thesis === "copper", `${where}.thesis`, "is neither empty nor the copper thesis");
  for (const name of [...PASSAGE_LISTS, "events"]) {
    const named: unknown[] = [];
    list(entry[name], `${where}.${name}`).forEach((value, at) => {
      const place = `${where}.${name}[${at}]`;
      const item = rec(value, place);
      sameKeys(item, name === "events" ? ["kind", "when", "passage", "evidence"] : ["passage", "evidence"], place);
      if (name === "events") filled(item.kind, `${place}.kind`);
      const evidence = checkCited(item, place, context.seen, name === "events");
      if (name === "events") {
        const when = text(item.when, `${place}.when`);
        need(when.length >= 4 && when.length <= 40 && when === when.trim() && YEAR.test(when), `${place}.when`,
          "is not a date of 4 to 40 characters with a year");
        need(evidence.state !== "verified" || (evidence.quote as string).includes(when), `${place}.when`,
          "is not in the event's verified quote");
      }
      need(!named.includes(item.passage), place, "names a passage already in this list");
      named.push(item.passage);
    });
  }
  list(entry.chains, `${where}.chains`).forEach((chain, at) => checkChain(chain, metal, `${where}.chains[${at}]`, context));
}

/** The research part: the fixed written-by sentence; withheld, no notes and the fixed problem; available, every link
 * resolved again from the USGS, risk and uses parts above (each already read) and every passage's fields checked. */
export function checkResearch(view: Record<string, unknown>) {
  const part = rec(view.research, "research");
  sameKeys(part, ["engine", "state", "problem", "written_by", "metals"], "research");
  need(part.engine === RESEARCH_ENGINE, "research.engine", "is not the expected engine");
  need(part.written_by === WRITTEN_BY, "research.written_by", "is not the fixed written-by sentence");
  const metals = rec(part.metals, "research.metals");
  if (part.state === "withheld") {
    need(part.problem === RESEARCH_PROBLEM, "research.problem", "is not the fixed reason the notes are withheld");
    need(Object.keys(metals).length === 0, "research.metals", "must be empty when withheld");
    return;
  }
  need(part.state === "available", "research.state", "is neither available nor withheld");
  need(part.problem === null, "research.problem", "must be empty when available");
  const usgs = view.usgs as { state: string; problem: string | null; chapters: Chapter[] };
  const risk = view.risk as { chapters: RiskChapter[] }, uses = view.uses as UsesPart;
  const resolver: Resolver = {
    usgs: usgs.state === "available" ? { chapters: new Map(usgs.chapters.map((item) => [item.id, item])),
      risk: new Map(risk.chapters.map((item) => [item.id, item])) } : null,
    usgsProblem: usgs.problem, uses: uses.state === "available" ? uses.entries as UseEntry[] : null,
    usesProblem: uses.problem,
  };
  const context: Context = { resolver, seen: new Map(), chains: new Set() };
  for (const [metal, entry] of Object.entries(metals)) {
    need(METAL_IDS.includes(metal), "research.metals", "names a metal that is not a USGS chapter");
    checkResearchMetal(entry, metal, `research.${metal}`, context);
  }
}

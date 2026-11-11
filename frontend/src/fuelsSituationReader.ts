// The fuels page's Situation Now, drivers, transmission and events parts (fuels-view-0.2), read fail-closed. Every
// Situation Now number is recomputed here exactly (BigInt fractions, copperNumbers.ts) from the three input series'
// own histories, mirroring second_order/fuels_situation.py: the windows, their rows, the percentage, the exact split
// and its label. Each shown text must be the half-even rounding of its exact value, and rounded values never feed
// later arithmetic. The mechanism parts get their shapes checked; the text rules stay with the server. A refusal
// names its place and rule, never a value.
import { add, div, equal, halfEven, int, lessThan, make, mul, ofPlain, sub, type Rat } from "./copperNumbers.ts";
import { isRec, refuse } from "./copperTools.ts";

export const SITUATION_VERSION = "fuels-situation-0.1";
export const MECHANISMS_VERSION = "fuels-mechanisms-0.1";
export const WINDOW_IDS = ["previous", "week", "month"] as const;
export const LABELS = ["unchanged", "offsetting", "mostly_crude", "mostly_crack", "both"] as const;
export const DRIVER_IDS = ["opec_supply", "global_demand", "inventories", "refining", "geopolitics", "shipping",
  "dollar_rates_growth", "seasonality"] as const;
export const SECTOR_IDS = ["aviation", "shipping_logistics", "refiners_energy", "chemicals", "agriculture",
  "consumer_retail", "inflation_policy"] as const;
export const ACTS_ON = ["crude", "crack", "both"] as const;
export const EFFECTS = ["negative", "positive", "mixed"] as const;
const WEEK_TOLERANCE_DAYS = 3;
const MONTH_TOLERANCE_DAYS = 5;
const STALE_DAYS = 10;
const ROLE_ORDER = ["brent", "wti", "gasoline", "diesel", "henry_hub"] as const;
const SERIES = ["brent", "gasoline", "diesel"] as const;
const ROW_NAMES = [...SERIES, "basket", "crack"] as const;
const PLACES: Record<string, number> = { brent: 2, gasoline: 3, diesel: 3, basket: 2, crack: 2 };
const TOP_FIELDS = ["mechanisms_version", "kind", "prepared_on", "author", "review", "items"];
const DRIVER_FIELDS = ["id", "title", "mechanism", "acts_on", "direction", "changes_when", "watch", "sources"];
const SECTOR_FIELDS = ["id", "sector", "trigger", "chain", "effect", "effect_text", "second_order", "flips_when",
  "lag", "lag_sourced", "sources"];
const SOURCE_FIELDS = ["title", "publisher", "date", "url", "checked_on", "locator"];

export interface PairView { value: string; shown: string }
export interface RowView { from: PairView; to: PairView; change: PairView; pct: { shown: string } | null }
export interface SplitView {
  crude: PairView; crack: PairView; basket: PairView; gasoline_part: PairView; diesel_part: PairView;
  label: (typeof LABELS)[number];
}
export interface WindowView {
  id: (typeof WINDOW_IDS)[number]; state: "computed" | "unavailable"; reason: string | null; target: string | null;
  from: string | null; to: string; rows: Record<(typeof ROW_NAMES)[number], RowView> | null; split: SplitView | null;
}
export interface SituationView {
  engine_version: string; state: "computed" | "withheld"; problem: string | null; date: string | null;
  age_days: number | null; stale: boolean; newer: { role: string; date: string }[]; windows: WindowView[];
}
export interface SourceItem {
  title: string; publisher: string; date: string | null; url: string; checked_on: string; locator: string | null;
}
export interface DriverItem {
  id: (typeof DRIVER_IDS)[number]; title: string; mechanism: string; acts_on: (typeof ACTS_ON)[number];
  direction: string[]; changes_when: string[]; watch: string[]; sources: SourceItem[];
}
export interface SectorItem {
  id: (typeof SECTOR_IDS)[number]; sector: string; trigger: string; chain: string[];
  effect: (typeof EFFECTS)[number]; effect_text: string; second_order: string[]; flips_when: string[]; lag: string;
  lag_sourced: boolean; sources: SourceItem[];
}
export type MechanismFile<T> =
  | { state: "not_written" }
  | { state: "written"; mechanisms_version: string; kind: string; prepared_on: string; author: string;
      review: { state: string; reviewed_on: string | null }; items: T[] };
export interface EventsView { state: "not_connected"; schema: string; text: string }

export type Hist = Record<string, Map<string, Rat | null>>;
export interface Parts {
  situation: unknown; drivers: unknown; transmission: unknown; events: unknown;
  snapshot: { retrieved_at: string | null };
  barrel: { state: string; date: string | null; previous_date: string | null };
  series: { role: string; latest: { date: string } | null }[];
}

function must(condition: unknown, where: string, rule: string): asserts condition {
  if (!condition) refuse(where, rule);
}
const isText = (value: unknown): value is string => typeof value === "string" && value !== "";
const isDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
const oneOf = (list: readonly string[], value: unknown) => typeof value === "string" && list.includes(value);
const exactKeys = (item: Record<string, unknown>, keys: readonly string[], where: string) =>
  must(Object.keys(item).length === keys.length && keys.every((key) => key in item), where, "has not exactly its fields");

function exact(value: unknown, where: string): Rat {
  const parsed = ofPlain(value);
  return parsed === null ? refuse(where, "is not a plain decimal") : parsed;
}
function checkPair(item: unknown, expected: Rat, places: number, where: string) {
  must(isRec(item), where, "is not a value");
  exactKeys(item, ["value", "shown"], where);
  must(equal(exact(item.value, where), expected), where, "does not follow its inputs");
  must(item.shown === halfEven(expected, places), where, "is not the half-even rounding of its value");
}

const dayNumber = (day: string) => Math.round(Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / 86400000);
const dayText = (n: number) => new Date(n * 86400000).toISOString().slice(0, 10);
/** The same day of the previous month, clamped to that month's length. */
export function monthBefore(day: string): string {
  let year = +day.slice(0, 4);
  let month = +day.slice(5, 7) - 1;
  if (month === 0) { year -= 1; month = 11; } else month -= 1;
  const length = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const clamped = String(Math.min(+day.slice(8, 10), length)).padStart(2, "0");
  return `${year}-${String(month + 1).padStart(2, "0")}-${clamped}`;
}

const abs = (a: Rat): Rat => (a.n < 0n ? make(-a.n, a.d) : a);
const sign = (a: Rat) => (a.n > 0n ? 1 : a.n < 0n ? -1 : 0);
/** The split label, as second_order/fuels_situation.split_label (inclusive 2/3 and 1/3 thresholds). */
export function splitLabel(crude: Rat, crack: Rat): string {
  if (sign(crude) === 0 && sign(crack) === 0) return "unchanged";
  if (sign(crude) * sign(crack) < 0) return "offsetting";
  const share = div(abs(crude), add(abs(crude), abs(crack)));
  if (!lessThan(share, make(2n, 3n))) return "mostly_crude";
  if (!lessThan(make(1n, 3n), share)) return "mostly_crack";
  return "both";
}

function levels(h: Hist, day: string): Record<string, Rat> {
  const out: Record<string, Rat> = {};
  for (const role of SERIES) out[role] = h[role].get(day) as Rat;
  out.basket = mul(int(14), add(mul(int(2), out.gasoline), out.diesel));
  out.crack = sub(out.basket, out.brent);
  return out;
}

function checkRow(row: unknown, name: string, old: Rat, now: Rat, where: string) {
  must(isRec(row), where, "is not a row");
  exactKeys(row, ["from", "to", "change", "pct"], where);
  const change = sub(now, old);
  checkPair(row.from, old, PLACES[name], `${where}.from`);
  checkPair(row.to, now, PLACES[name], `${where}.to`);
  checkPair(row.change, change, PLACES[name], `${where}.change`);
  if (name === "crack" || old.n <= 0n) {
    must(row.pct === null, `${where}.pct`, "is shown although it is not defined");
    return;
  }
  must(isRec(row.pct), `${where}.pct`, "is missing");
  exactKeys(row.pct, ["shown"], `${where}.pct`);
  must(row.pct.shown === halfEven(mul(div(change, old), int(100)), 1), `${where}.pct`,
       "is not the half-even rounding of the change over its start");
}

function checkSplit(split: unknown, old: Record<string, Rat>, now: Record<string, Rat>, where: string) {
  must(isRec(split), where, "is not a split");
  exactKeys(split, ["crude", "crack", "basket", "gasoline_part", "diesel_part", "label"], where);
  const crude = sub(now.brent, old.brent);
  const crack = sub(now.crack, old.crack);
  const gasolinePart = mul(int(28), sub(now.gasoline, old.gasoline));
  const dieselPart = mul(int(14), sub(now.diesel, old.diesel));
  const basket = sub(now.basket, old.basket);
  checkPair(split.crude, crude, 2, `${where}.crude`);
  checkPair(split.crack, crack, 2, `${where}.crack`);
  checkPair(split.basket, basket, 2, `${where}.basket`);
  checkPair(split.gasoline_part, gasolinePart, 2, `${where}.gasoline_part`);
  checkPair(split.diesel_part, dieselPart, 2, `${where}.diesel_part`);
  must(equal(add(crude, crack), basket) && equal(add(gasolinePart, dieselPart), basket), where,
       "parts do not sum to the basket change");
  must(split.label === splitLabel(crude, crack), `${where}.label`, "does not follow the split");
}

/** The latest date on or before `target` (or before `latest` when target is null) within the tolerance, else null. */
function startOf(dates: string[], latest: string, target: string | null, tolerance: number): string | null {
  const earlier = dates.filter((day) => (target === null ? day < latest : day <= target));
  if (earlier.length === 0) return null;
  const start = earlier[earlier.length - 1];
  if (target !== null && dayNumber(target) - dayNumber(start) > tolerance) return null;
  return start;
}

function checkWindow(item: unknown, id: string, h: Hist, dates: string[], latest: string, where: string) {
  must(isRec(item), where, "is not a window");
  exactKeys(item, ["id", "state", "reason", "target", "from", "to", "rows", "split"], where);
  must(item.id === id, `${where}.id`, "is not the expected window");
  const target = id === "previous" ? null : id === "week" ? dayText(dayNumber(latest) - 7) : monthBefore(latest);
  const tolerance = id === "week" ? WEEK_TOLERANCE_DAYS : MONTH_TOLERANCE_DAYS;
  must(item.target === target, `${where}.target`, "is not the window's target date");
  must(item.to === latest, `${where}.to`, "is not the barrel date");
  const start = startOf(dates, latest, target, tolerance);
  if (item.state === "unavailable") {
    must(start === null, `${where}.state`, "is unavailable although a common date is within tolerance");
    must(isText(item.reason), `${where}.reason`, "does not say why the window is unavailable");
    must(item.from === null && item.rows === null && item.split === null, where, "shows values although unavailable");
    return;
  }
  must(item.state === "computed", `${where}.state`, "is unknown");
  must(start !== null, `${where}.state`, "is computed without a common date within tolerance");
  must(item.reason === null, `${where}.reason`, "is set on a computed window");
  must(item.from === start, `${where}.from`, "is not the latest common date within tolerance");
  const old = levels(h, start);
  const now = levels(h, latest);
  must(isRec(item.rows), `${where}.rows`, "is not a set of rows");
  exactKeys(item.rows, ROW_NAMES, `${where}.rows`);
  for (const name of ROW_NAMES) checkRow(item.rows[name], name, old[name], now[name], `${where}.rows.${name}`);
  checkSplit(item.split, old, now, `${where}.split`);
}

function checkWithheld(situation: SituationView, barrel: Parts["barrel"]) {
  must(isText(situation.problem), "situation.problem", "is withheld without saying why");
  must(barrel.state === "withheld", "situation", "is withheld beside a computed barrel");
  must(situation.date === null && situation.age_days === null && situation.stale === false, "situation",
       "shows a value although it is withheld");
  must(Array.isArray(situation.windows) && situation.windows.length === 0, "situation.windows",
       "has windows although it is withheld");
  must(Array.isArray(situation.newer) && situation.newer.length === 0, "situation.newer",
       "has entries although it is withheld");
}

function checkSituation(parts: Parts, h: Hist | null) {
  const situation = parts.situation as SituationView;
  must(isRec(situation), "situation", "is not an object");
  exactKeys(situation, ["engine_version", "state", "problem", "date", "age_days", "stale", "newer", "windows"], "situation");
  must(situation.engine_version === SITUATION_VERSION, "situation.engine_version", "is not the supported version");
  must(oneOf(["computed", "withheld"], situation.state), "situation.state", "is unknown");
  if (situation.state === "withheld") return checkWithheld(situation, parts.barrel);
  const barrel = parts.barrel;
  must(barrel.state === "computed" && h !== null, "situation", "is computed beside a withheld barrel");
  must(situation.problem === null, "situation.problem", "is set on a computed situation");
  const latest = barrel.date as string;
  must(situation.date === latest, "situation.date", "is not the barrel date");
  const retrieved = parts.snapshot.retrieved_at;
  must(isText(retrieved) && isDate(retrieved.slice(0, 10)), "situation.age_days", "has no retrieval date to count from");
  const age = dayNumber(retrieved.slice(0, 10)) - dayNumber(latest);
  must(situation.age_days === age, "situation.age_days", "is not the days from the barrel date to retrieval");
  must(situation.stale === age > STALE_DAYS, "situation.stale", "does not follow the age");
  const newer = ROLE_ORDER.flatMap((role) => {
    const day = parts.series.find((row) => row.role === role)?.latest?.date;
    return day !== undefined && day > latest ? [{ role, date: day }] : [];
  });
  must(Array.isArray(situation.newer) && situation.newer.length === newer.length &&
       newer.every((entry, index) => {
         const got = situation.newer[index];
         return isRec(got) && Object.keys(got).length === 2 && got.role === entry.role && got.date === entry.date;
       }), "situation.newer", "is not exactly the roles whose latest observation is after the barrel date");
  const dates = [...h.brent.keys()].filter((day) => SERIES.every((role) => h[role].get(day) != null));
  must(Array.isArray(situation.windows) && situation.windows.length === WINDOW_IDS.length, "situation.windows",
       "is not exactly the three windows");
  WINDOW_IDS.forEach((id, index) => checkWindow(situation.windows[index], id, h, dates, latest, `situation.windows[${index}]`));
  const previous = situation.windows[0];
  must(previous.state === "computed" ? previous.from === barrel.previous_date : barrel.previous_date === null,
       "situation.windows[0].from", "is not the barrel's previous date");
}

function checkTexts(list: unknown, where: string, minimum: number) {
  must(Array.isArray(list) && list.length >= minimum && list.every(isText), where, "is not a list of text");
}

function checkSources(list: unknown, where: string) {
  must(Array.isArray(list), where, "is not a list");
  list.forEach((source, index) => {
    const at = `${where}[${index}]`;
    must(isRec(source), at, "is not a source");
    exactKeys(source, SOURCE_FIELDS, at);
    must(isText(source.title) && isText(source.publisher), at, "lacks a title or publisher");
    must(typeof source.url === "string" && source.url.startsWith("https://"), `${at}.url`, "is not an https address");
    must(source.date === null || isDate(source.date), `${at}.date`, "is not a date");
    must(isDate(source.checked_on), `${at}.checked_on`, "is not a date");
    must(source.locator === null || isText(source.locator), `${at}.locator`, "is not text");
  });
}

function checkItem(item: unknown, id: string, fields: string[], where: string): Record<string, unknown> {
  must(isRec(item) && item.id === id, `${where}.id`, "is not the expected item in its fixed order");
  exactKeys(item, fields, where);
  return item;
}

function checkMechanism(part: unknown, name: string, kind: string, ids: readonly string[], fields: string[],
                        checkOne: (item: Record<string, unknown>, where: string) => void) {
  must(isRec(part), name, "is not an object");
  if (part.state === "not_written") {
    exactKeys(part, ["state"], name);
    return;
  }
  must(part.state === "written", `${name}.state`, "is unknown");
  exactKeys(part, ["state", ...TOP_FIELDS], name);
  must(part.mechanisms_version === MECHANISMS_VERSION, `${name}.mechanisms_version`, "is not the supported version");
  must(part.kind === kind, `${name}.kind`, "is not the expected kind");
  must(isDate(part.prepared_on) && isText(part.author), name, "lacks its preparation date or author");
  const review = part.review;
  must(isRec(review) && oneOf(["unreviewed", "reviewed"], review.state), `${name}.review`, "is not a review state");
  must(review.reviewed_on === null || isDate(review.reviewed_on), `${name}.review.reviewed_on`, "is not a date");
  const items = part.items;
  must(Array.isArray(items) && items.length === ids.length, `${name}.items`, "is not exactly the listed items");
  ids.forEach((id, index) => {
    const where = `${name}.items[${index}]`;
    checkOne(checkItem(items[index], id, fields, where), where);
  });
}

function checkDriver(item: Record<string, unknown>, where: string) {
  must(isText(item.title) && isText(item.mechanism), where, "lacks its title or mechanism");
  must(oneOf(ACTS_ON, item.acts_on), `${where}.acts_on`, "is not a listed value");
  for (const name of ["direction", "changes_when", "watch"]) checkTexts(item[name], `${where}.${name}`, 1);
  checkSources(item.sources, `${where}.sources`);
}

function checkSector(item: Record<string, unknown>, where: string) {
  must(isText(item.sector) && isText(item.trigger) && isText(item.effect_text) && isText(item.lag), where,
       "lacks a required text");
  checkTexts(item.chain, `${where}.chain`, 3);
  must(oneOf(EFFECTS, item.effect), `${where}.effect`, "is not a listed value");
  for (const name of ["second_order", "flips_when"]) checkTexts(item[name], `${where}.${name}`, 1);
  must(typeof item.lag_sourced === "boolean", `${where}.lag_sourced`, "is not true or false");
  checkSources(item.sources, `${where}.sources`);
}

/** The Situation Now, drivers, transmission and events parts; refuses at the first place that breaks a rule. */
export function checkViewParts(parts: Parts, histories: Hist | null) {
  checkSituation(parts, histories);
  checkMechanism(parts.drivers, "drivers", "drivers", DRIVER_IDS, DRIVER_FIELDS, checkDriver);
  checkMechanism(parts.transmission, "transmission", "transmission", SECTOR_IDS, SECTOR_FIELDS, checkSector);
  const events = parts.events;
  must(isRec(events) && events.state === "not_connected", "events.state", "is not not_connected");
  must(isText(events.schema) && isText(events.text), "events", "lacks its schema or text");
}

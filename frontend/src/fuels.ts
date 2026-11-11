// The fuels page's reply (/api/fuels, fuels-view-0.5, second_order/fuels_view.py; prices from EIA), read fail-closed. A value appears
// only on a verified series; a snapshot that is not verified withholds every value; the barrel's basket, crack and
// changes are recomputed here exactly (BigInt fractions, copperNumbers.ts) from the three input series' own histories
// and must equal what the server shows, each shown text being the half-even rounding of its exact value; every crack
// history row is recomputed too. Each refusal names its place and rule, never a value. Nothing here requests anything
// outside this server. 0.5: each verified series' "behind" (more than ten days older than the newest latest observation
// on the page) is recomputed from the latest dates, and a barrel computed beside an input that is behind is refused.
import type { Loaded } from "./api";
import { add, equal, halfEven, int, mul, ofPlain, sub, type Rat } from "./copperNumbers.ts";
import { isRec, Refusal, refuse } from "./copperTools.ts";
import { checkViewParts } from "./fuelsSituationReader.ts";
import type { DriverItem, EventsView, MechanismFile, SectorItem, SituationView } from "./fuelsSituationReader.ts";

export type * from "./fuelsSituationReader.ts";

export const FUELS_VIEW_VERSION = "fuels-view-0.5";
export const SNAPSHOT_STATES = ["verified", "missing", "changed"] as const;
export const SERIES_STATES = ["verified", "missing", "refused", "terms_changed"] as const;
export const KINDS = ["published", "missing"] as const;
export const NOTE_STATES = ["current", "earlier", "unbound"] as const;
export const ROLES = ["brent", "wti", "gasoline", "diesel", "henry_hub"] as const;
const BARREL_ROLES = ["brent", "gasoline", "diesel"] as const;
const UNIT_PLACES: Record<string, number> = { usd_per_bbl: 2, usd_per_gal: 3, usd_per_mmbtu: 2 };
const INPUT_PLACES = { brent: 2, gasoline: 3, diesel: 3 };
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";
const BEHIND_DAYS = 10;

export type SeriesState = (typeof SERIES_STATES)[number];
export type Role = (typeof ROLES)[number];

export interface Pair { value: string; shown: string }
/** published_on is EIA's publication date, which its API does not give: null, shown as missing, never inferred. */
export interface Latest { date: string; value: string; shown: string; published_on: string | null }
export interface SeriesView {
  series_id: string; role: Role; label: string; unit: string; cadence: string; publication: string; scope: string;
  basis: string; public: string; state: SeriesState; problem: string | null; kind: "published" | "missing";
  attribution: unknown; url: string; data_vendor: { name: string; term: string } | null; release: unknown;
  latest: Latest | null;
  /** Set on a verified series whose latest observation is more than ten days older than the newest on the page. */
  behind: { days: number; newest: string } | null;
  history: [string, string | null][];
}
export type Inputs = { brent: Pair; gasoline: Pair; diesel: Pair };
export interface BarrelView {
  engine_version: string; state: "computed" | "withheld"; problem: string | null; date: string | null;
  previous_date: string | null; inputs: Inputs | null; previous: Inputs | null; basket: Pair | null;
  crack: (Pair & { sign: "positive" | "negative" | "zero" }) | null;
  change: { brent: Pair; basket: Pair; crack: Pair } | null; published_on: string | null; retrieved_at: string | null;
  definition: { basket: string; crack: string; unit: string };
}
export interface NoteView {
  state: "current" | "earlier" | "unbound" | "none"; problem?: string | null;
  then?: { brent: string; crack: string } | null; now?: { brent: string; crack: string } | null;
  snapshot_id?: string; [field: string]: unknown;
}
export interface FuelsView {
  view_version: string; provider_called: false; page_label: string; credit: string; terms: unknown;
  /** Present, and true, only for the review server's SYNTHETIC world or a snapshot from the test fake: the page then
   * marks every price as test data. */
  synthetic?: true;
  sources: { version: string; sha256: string };
  snapshot: { state: (typeof SNAPSHOT_STATES)[number]; problem: string | null; id: string | null;
    retrieved_at: string | null; retrieved_on: string | null; provider: string | null; adapter_version: string | null };
  snapshots: { id: string; retrieved_at: string; retrieved_on: string | null; provider: string | null; stored: number;
    refused: number }[];
  series: SeriesView[]; barrel: BarrelView; crack_history: [string, string][]; note: NoteView;
  notes: { number: number; state: string; written_on: string; snapshot_id: string; observation_date: string;
    review: unknown }[];
  coverage: { id: string; label: string; cadence: string; source: string; series_id: string | null; state: string;
    problem: string | null }[];
  example: Record<string, string>; labels: Record<string, Record<string, string>>;
  situation: SituationView; drivers: MechanismFile<DriverItem>; transmission: MechanismFile<SectorItem>;
  events: EventsView;
}

function must(condition: unknown, where: string, rule: string): asserts condition {
  if (!condition) refuse(where, rule);
}
const oneOf = (list: readonly string[], value: unknown) => typeof value === "string" && list.includes(value);
export const isText = (value: unknown): value is string => typeof value === "string" && value !== "";
const isDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);

/** The exact value of a plain decimal text, else a refusal at `where`. */
function exact(value: unknown, where: string): Rat {
  const parsed = ofPlain(value);
  return parsed === null ? refuse(where, "is not a plain decimal") : parsed;
}

function checkPair(item: unknown, expected: Rat, places: number, where: string) {
  must(isRec(item), where, "is not a value");
  must(equal(exact(item.value, where), expected), where, "does not follow its inputs");
  must(item.shown === halfEven(expected, places), where, "is not the half-even rounding of its value");
}

/** A series' history as exact values by date; the dates must ascend. */
function historyOf(row: SeriesView, where: string): Map<string, Rat | null> {
  must(Array.isArray(row.history), `${where}.history`, "is not a list");
  const out = new Map<string, Rat | null>();
  let last = "";
  for (const point of row.history) {
    must(Array.isArray(point) && point.length === 2 && isDate(point[0]), `${where}.history`, "holds a malformed point");
    must(point[0] > last, `${where}.history`, "does not ascend by date");
    last = point[0];
    out.set(point[0], point[1] === null ? null : exact(point[1], `${where}.history`));
  }
  return out;
}

function checkSeries(row: unknown, where: string): SeriesView {
  must(isRec(row), where, "is not a series");
  const view = row as unknown as SeriesView;
  must(oneOf(ROLES, view.role), where, "has an unknown role");
  must(oneOf(SERIES_STATES, view.state), where, "has an unknown state");
  must(oneOf(KINDS, view.kind), where, "has an unknown kind");
  must(view.unit in UNIT_PLACES, where, "has an unknown unit");
  const verified = view.state === "verified";
  must(view.kind === (verified ? "published" : "missing"), where, "kind does not match its state");
  must("behind" in view, where, "has no behind field");
  must(verified || view.behind === null, `${where}.behind`, "is set although the series is not verified");
  must(verified === (view.latest !== null), where, "has a latest value only when verified");
  const history = historyOf(view, where);
  if (!verified) {
    must(history.size === 0, where, "shows a history although it is not verified");
    must(isText(view.problem), where, "does not say why it is not verified");
    return view;
  }
  const latest = view.latest as Latest;
  must(isRec(latest) && isDate(latest.date), `${where}.latest`, "is not a dated value");
  const valued = [...history].filter(([, value]) => value !== null);
  must(valued.length > 0 && valued[valued.length - 1][0] === latest.date, `${where}.latest`,
       "is not the last value in its history");
  const value = exact(latest.value, `${where}.latest`);
  must(equal(value, valued[valued.length - 1][1] as Rat), `${where}.latest`, "does not equal its history");
  must(latest.shown === halfEven(value, UNIT_PLACES[view.unit]), `${where}.latest`,
       "is not the half-even rounding of its value");
  must(latest.published_on === null || isDate(latest.published_on), `${where}.latest`, "has a malformed publication date");
  return view;
}

const dayNumber = (day: string) =>
  Math.round(Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / 86400000);

/** Each verified series' lag behind the newest latest observation on the page must be exactly what the dates give. */
function checkBehind(series: SeriesView[]) {
  const dates = series.flatMap((row) => (row.latest ? [row.latest.date] : []));
  const newest = dates.reduce((a, b) => (a > b ? a : b), "");
  series.forEach((row, index) => {
    const days = row.latest ? dayNumber(newest) - dayNumber(row.latest.date) : 0;
    const expected = days > BEHIND_DAYS ? { days, newest } : null;
    const got = row.behind;
    const same = expected === null ? got === null
      : isRec(got) && Object.keys(got).length === 2 && got.days === expected.days && got.newest === expected.newest;
    must(same, `series[${index}].behind`, "does not follow the latest dates");
  });
}

const basketOf = (g: Rat, d: Rat) => mul(int(14), add(mul(int(2), g), d));
const crackOf = (g: Rat, d: Rat, b: Rat) => sub(basketOf(g, d), b);

type Histories = Record<(typeof BARREL_ROLES)[number], Map<string, Rat | null>>;

/** Ascending dates on which all three input histories have a value. */
function commonDates(h: Histories): string[] {
  return [...h.brent.keys()].filter((day) => BARREL_ROLES.every((role) => h[role].get(day) != null));
}

function checkInputs(item: unknown, h: Histories, day: string, where: string): Record<string, Rat> {
  must(isRec(item), where, "is not the three inputs");
  const values: Record<string, Rat> = {};
  for (const role of BARREL_ROLES) {
    const pair = item[role];
    must(isRec(pair), `${where}.${role}`, "is not a value");
    const value = exact(pair.value, `${where}.${role}`);
    must(equal(value, h[role].get(day) as Rat), `${where}.${role}`, "is not its series' value on that date");
    must(pair.shown === halfEven(value, INPUT_PLACES[role]), `${where}.${role}`,
         "is not the half-even rounding of its value");
    values[role] = value;
  }
  return values;
}

function checkWithheld(barrel: BarrelView) {
  must(isText(barrel.problem), "barrel", "is withheld without saying why");
  for (const field of ["date", "previous_date", "inputs", "previous", "basket", "crack", "change", "published_on"] as const) {
    must(barrel[field] === null, `barrel.${field}`, "shows a value although the barrel is withheld");
  }
}

function checkBarrel(barrel: BarrelView, rows: Map<string, SeriesView>, snapshotState: string): Histories | null {
  must(isRec(barrel) && oneOf(["computed", "withheld"], barrel.state), "barrel", "has an unknown state");
  if (barrel.state === "withheld") {
    checkWithheld(barrel);
    return null;
  }
  must(snapshotState === "verified", "barrel", "is computed although the snapshot is not verified");
  must(BARREL_ROLES.every((role) => rows.get(role)?.state === "verified"), "barrel", "is computed from an unverified series");
  must(BARREL_ROLES.every((role) => rows.get(role)?.behind === null), "barrel",
       "is computed from a series more than ten days behind the newest price");
  must(barrel.problem === null, "barrel.problem", "is set on a computed barrel");
  const h = Object.fromEntries(BARREL_ROLES.map((role) => [role, historyOf(rows.get(role) as SeriesView, role)])) as Histories;
  const dates = commonDates(h);
  must(isDate(barrel.date) && dates[dates.length - 1] === barrel.date, "barrel.date",
       "is not the latest date all three inputs share");
  const now = checkInputs(barrel.inputs, h, barrel.date, "barrel.inputs");
  const basket = basketOf(now.gasoline, now.diesel);
  const spread = sub(basket, now.brent);
  checkPair(barrel.basket, basket, 2, "barrel.basket");
  checkPair(barrel.crack, spread, 2, "barrel.crack");
  const sign = spread.n > 0n ? "positive" : spread.n < 0n ? "negative" : "zero";
  must(barrel.crack?.sign === sign, "barrel.crack.sign", "does not match the crack");
  const before = dates.length > 1 ? dates[dates.length - 2] : null;
  must(barrel.previous_date === before, "barrel.previous_date", "is not the previous date all three inputs share");
  if (before === null) {
    must(barrel.previous === null && barrel.change === null, "barrel.change", "shows a change without a previous date");
    return h;
  }
  const then = checkInputs(barrel.previous, h, before, "barrel.previous");
  const change = barrel.change;
  must(isRec(change), "barrel.change", "is missing");
  checkPair(change.brent, sub(now.brent, then.brent), 2, "barrel.change.brent");
  checkPair(change.basket, sub(basket, basketOf(then.gasoline, then.diesel)), 2, "barrel.change.basket");
  checkPair(change.crack, sub(spread, crackOf(then.gasoline, then.diesel, then.brent)), 2, "barrel.change.crack");
  return h;
}

function checkCrackHistory(view: FuelsView, h: Histories | null) {
  const rows = view.crack_history;
  must(Array.isArray(rows), "crack_history", "is not a list");
  if (h === null) {
    must(rows.length === 0, "crack_history", "has rows although the barrel is withheld");
    return;
  }
  const since = BARREL_ROLES.map((role) => [...h[role].keys()][0]).reduce((a, b) => (a > b ? a : b));
  const expected = commonDates(h).filter((day) => day >= since);
  must(rows.length === expected.length, "crack_history", "does not cover exactly the dates of the input histories");
  expected.forEach((day, index) => {
    const row = rows[index];
    const where = `crack_history[${index}]`;
    must(Array.isArray(row) && row.length === 2 && row[0] === day, where, "is not the expected date");
    must(equal(exact(row[1], where), crackOf(h.gasoline.get(day) as Rat, h.diesel.get(day) as Rat,
                                             h.brent.get(day) as Rat)), where, "does not follow the histories");
  });
}

const isShownPair = (item: unknown): item is { brent: string; crack: string } =>
  isRec(item) && typeof item.brent === "string" && typeof item.crack === "string";

function checkNote(view: FuelsView) {
  const note = view.note;
  must(isRec(note), "note", "is not a note");
  if (note.state === "none") return;
  must(oneOf(NOTE_STATES, note.state), "note.state", "is unknown");
  const verified = view.snapshot.state === "verified";
  if (note.state === "current") {
    must(verified && note.snapshot_id === view.snapshot.id, "note.snapshot_id",
         "is not the snapshot the page shows although the note is current");
    must(note.then === null && note.now === null, "note", "compares a current note");
    return;
  }
  if (note.state === "unbound") {
    must(note.then === null && note.now === null && isText(note.problem), "note", "is unbound without its reason");
    return;
  }
  must(!verified || note.snapshot_id !== view.snapshot.id, "note.snapshot_id", "is the latest snapshot");
  must(isShownPair(note.then), "note.then", "is not the shown Brent and crack");
  const barrel = view.barrel;
  if (barrel.state === "computed") {
    must(isShownPair(note.now) && note.now.brent === barrel.inputs?.brent.shown && note.now.crack === barrel.crack?.shown,
         "note.now", "is not the latest barrel's shown Brent and crack");
  } else {
    must(note.now === null && isText(note.problem), "note.now", "is shown although the latest barrel is withheld");
  }
}

/** Null when the reply passes every check, else the first refusal's place and rule. */
export function fuelsRefusal(body: unknown): string | null {
  try {
    must(isRec(body), "reply", "is not an object");
    const view = body as unknown as FuelsView;
    must(view.view_version === FUELS_VIEW_VERSION, "view_version", `expected ${FUELS_VIEW_VERSION}`);
    must(view.provider_called === false, "provider_called", "a read never calls a provider");
    must(!("synthetic" in view) || view.synthetic === true, "synthetic", "is present but not true");
    must(isRec(view.snapshot) && oneOf(SNAPSHOT_STATES, view.snapshot.state), "snapshot.state", "is unknown");
    must(Array.isArray(view.series), "series", "is not a list");
    const rows = new Map<string, SeriesView>();
    view.series.forEach((row, index) => {
      const checked = checkSeries(row, `series[${index}]`);
      must(!rows.has(checked.role), `series[${index}]`, "repeats a role");
      rows.set(checked.role, checked);
    });
    must(BARREL_ROLES.every((role) => rows.has(role)), "series", "lacks an input of the barrel");
    checkBehind(view.series);
    if (view.snapshot.state !== "verified") {
      must([...rows.values()].every((row) => row.state !== "verified"), "series", "is verified although the snapshot is not");
      must(isRec(view.barrel) && view.barrel.state === "withheld", "barrel", "is not withheld although the snapshot is not verified");
    }
    const histories = checkBarrel(view.barrel, rows, view.snapshot.state);
    checkCrackHistory(view, histories);
    checkNote(view);
    checkViewParts(view, histories);
    must(Array.isArray(view.notes) && view.notes.every((row) => isRec(row) && oneOf(NOTE_STATES, row.state)), "notes",
         "holds a row with an unknown state");
    return null;
  } catch (error) {
    if (error instanceof Refusal) return error.message;
    if (error instanceof TypeError || error instanceof RangeError) return `reply: is not shaped as expected (${error.name})`;
    throw error;
  }
}

export async function fetchFuels(signal: AbortSignal): Promise<Loaded<FuelsView>> {
  let response: Response;
  try {
    response = await fetch("/api/fuels", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRec(body) && typeof body.detail === "string" ? body.detail : `Unexpected response (${response.status}).`;
    return { state: response.status === 503 ? "not-prepared" : "error", message };
  }
  const refusal = fuelsRefusal(body);
  return refusal === null ? { state: "ready", data: body as FuelsView }
    : { state: "error", message: `The reply could not be read by this page (${refusal}).` };
}

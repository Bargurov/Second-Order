// Committed theses (/api/theses/:id and /api/theses/:id/versions/:n): one version of a thesis, every figure and passage
// checked by the server against the retained sources on this machine, each element given a state, and what is not
// available withheld (thesis-view-0.1, second_order/thesis_view.py). Replies are read fail-closed: an element's state
// must follow from its sources' states and the items not found where cited; a withheld element shows its frame only;
// statuses, gaps, weeks of demand, costs and shares must follow from the figures they come from, compared as exact
// decimals (BigInt, never floating point); a figure must read the same wherever it is shown; counts must reconcile
// with the states; and the versions, the draft flag and the publication date must agree. Each refusal names its place
// and rule, never a value. Nothing here requests anything outside this server.
import type { Loaded } from "./api";
import { formatDay, monthLabel } from "./format.ts";
import {
  abs, difference, displayedPattern, displayedValue, halfEven, plainDecimal, pow10, printed, scaled, sign, type Dec,
} from "./thesisNumbers.ts";

export const THESIS_VIEW_VERSION = "thesis-view-0.1";
export const THESIS_VERSION = "thesis-0.1";
export const SOURCE_STATES = ["verified", "changed", "missing"] as const;
export const ELEMENT_STATES = ["available", "needs_revalidation", "unavailable"] as const;
export const STATEMENT_STATUSES = ["stated", "interpretation", "not_stated"] as const;
export const REASON_STATES = ["strengthening", "weakening", "unchanged"] as const;
export const RISK_STATES = ["materialising", "receding", "unchanged", "not_tracked"] as const;
export const CONDITION_STATES = ["happened", "not_happened"] as const;
export const SIDES = ["producer", "consumer"] as const;
export const UNITS = ["kt", "million_t", "t", "kg", "kg_per_unit", "usd_per_tonne", "usd_per_lb", "usd_cents_per_lb", "usd",
  "usd_million", "percent", "count"] as const;
export const CONFIDENCE_LEVELS = ["low", "medium", "high"] as const;
export const PLAIN_KEYS = ["view", "balance", "differs", "reasons", "risks", "conditions", "exposure", "log",
  "price"] as const;
const KINDS = ["html", "xlsx", "csv", "pdf"] as const;
const ORIGINS = ["get", "owner_download"] as const;
const GAPS = ["computed", "not_computed"] as const;
const ROW_KINDS = ["historical", "projection"] as const;
const COMPARES = ["revision", "period"] as const;
const DIRECTIONS = ["higher", "lower"] as const;
const COMPARATORS = ["below", "above"] as const;
const LOG_KINDS = ["opened", "status", "view", "confidence", "note"] as const;
const LABEL_GROUPS = { statuses: STATEMENT_STATUSES, source_states: SOURCE_STATES, element_states: ELEMENT_STATES,
  reason_states: REASON_STATES, risk_states: RISK_STATES, condition_states: CONDITION_STATES, sides: SIDES,
  units: UNITS } as const;
const VIEW_ID = "view";
const PRICE_RECORD_ID = "price-record";
/** How a PDF was read (ruling R17): exactly these two, printed verbatim. */
export const TRANSCRIPTION_METHODS = ["transcribed from the page image", "transcribed from the PDF's text layer"] as const;
const PRICE_UNITS = ["usd_per_tonne", "usd_cents_per_lb"] as const; // The price record's units (R18), never mixed.
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SHA = /^[0-9a-f]{64}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const YEAR = /^\d{4}$/;
const PERIOD = /^\d{4}(?:M(?:0[1-9]|1[0-2])|Q[1-4]|-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))$/;
const VERSION_NUMBER = /^[1-9][0-9]{0,3}$/;
const DIGIT = /\p{Nd}/u;  // Python's \d, which the server's withholding of titles uses (ruling R9).
const WHERE = { html: /^paragraph [1-9]\d*$/, pdf: /^page ([1-9]\d*) \(transcribed from the PDF\)$/,
  xlsx: /^sheet .+, cell [A-Z]{1,3}[1-9]\d{0,6}$/, csv: /^row [1-9]\d*, column .+$/ };
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";
const NO_VERSION = "This thesis has no such version";

export type SourceState = (typeof SOURCE_STATES)[number];
export type ElementState = (typeof ELEMENT_STATES)[number];
export type StatementStatus = (typeof STATEMENT_STATUSES)[number];
export type ReasonState = (typeof REASON_STATES)[number];
export type RiskState = (typeof RISK_STATES)[number];
export type ConditionState = (typeof CONDITION_STATES)[number];
export type Side = (typeof SIDES)[number];
export type Unit = (typeof UNITS)[number];
export type SourceKind = (typeof KINDS)[number];
export type Direction = (typeof DIRECTIONS)[number];

/** A figure as the server shows it: `value` is the plain decimal, `as_shown` the source's print. */
export interface Figure {
  id: string; value: string; as_shown: string; unit: Unit; year: string | null; period: string | null;
  basis: string | null; scenario: string | null; source: string; where: string; measure: string; quote: string | null;
}
export interface Passage { id: string; source: string; quote: string; where: string }
export interface Statement { status: StatementStatus; text: string; cites: string[]; figures: Figure[];
  passages: Passage[] }
export interface Item { id: string; source: string }
/** What every element carries in every state: what it was checked against, its state and why. */
export interface ElementCheck { items: Item[]; sources: string[]; state: ElementState; problems: string[];
  not_found: string[] }
export interface ViewElement extends ElementCheck { id: "view"; statement: Statement | null }
export interface BalanceRow {
  year: string; kind: (typeof ROW_KINDS)[number]; demand_total: Figure; supply_total: Figure;
  lines: { label: string; figure: Figure }[]; gap: string | null; label: "surplus" | "deficit" | "balanced" | null;
  weeks: string | null;
}
export interface BalanceTable extends ElementCheck { id: string; title: string | null; gap: (typeof GAPS)[number];
  why_not: string | null; rows: BalanceRow[] | null }
export interface Other { cite: string; label: string; figure: Figure | null; passage: Passage | null }
export interface Differs extends ElementCheck { id: string; about: Statement | null; others: Other[] | null;
  differs: boolean | null }
interface Measured { latest: Figure; previous: Figure; compare: (typeof COMPARES)[number]; material_change_pct: string }
export interface MovedBy { source: string; publisher: string; edition: string; edition_date: string }
interface Claim extends ElementCheck { id: string; title: string | null; plain: string; statement: Statement | null;
  change_pct: string | null; moved_by: MovedBy | null }
export interface Reason extends Claim { measure: (Measured & { supports_when: Direction }) | null;
  status: ReasonState | null }
export interface Risk extends Claim { measure: (Measured & { grows_when: Direction }) | null; status: RiskState | null }
export interface Condition extends ElementCheck { id: string; threshold_value: string | null;
  comparator: (typeof COMPARATORS)[number] | null; text: string | null; figure: Figure | null;
  threshold: string | null; status: ConditionState | null }
export interface Mover extends ElementCheck { id: string; company: string; moves: string; through: string | null;
  cites: string[] | null; figures: Figure[] | null; passages: Passage[] | null }
export type Amount = { kind: "stated"; figure: Figure }
  | { kind: "computed"; per_unit: Figure; price: Figure; unit_price: Figure | null };
export interface Moved extends ElementCheck { id: string; company: string; side: Side; how: Statement | null;
  amount: Amount | null; usd_per_unit: string | null; share_pct: string | null }
export interface PriceRecord extends ElementCheck { id: "price-record"; series: string | null; opening: Figure | null;
  latest: Figure | null }
export type ThesisElement = ViewElement | BalanceTable | Differs | Reason | Risk | Condition | Mover | Moved
  | PriceRecord;
export interface ThesisSource {
  id: string; publisher: string; title: string; edition: string; edition_date: string; url: string; kind: SourceKind;
  origin: (typeof ORIGINS)[number]; terms: { licence: string; note: string };
  transcription: { pages: number[]; method: string } | null; retrieved_at: string; sha256: string;
  state: SourceState; detail: string;
}
export interface LogEntry { date: string; kind: (typeof LOG_KINDS)[number]; text: string; refs: string[] }
export interface ThesisView {
  view_version: string; thesis_version: string; id: string; version: number;
  versions: { version: number; published_on: string | null }[]; draft: boolean; title: string; topic: string;
  opened_on: string; prepared_on: string; published_on: string | null;
  confidence: { level: (typeof CONFIDENCE_LEVELS)[number]; basis: string }; provider_called: false;
  labels: { [Group in keyof typeof LABEL_GROUPS]: Record<(typeof LABEL_GROUPS)[Group][number], string> };
  sources: ThesisSource[]; view: ViewElement; balance: { tables: BalanceTable[] }; differs: Differs[];
  reasons: Reason[]; risks: Risk[]; conditions: Condition[]; exposure: { movers: Mover[]; moved: Moved[] };
  price_record: PriceRecord; log: LogEntry[]; plain: Record<(typeof PLAIN_KEYS)[number], string>;
  not_claimed: string[];
  provenance: { prepared_by: string; method: string; ai_assisted: true; human_review: "not_reviewed";
    research_use: "excluded" };
  counts: { sources: Record<SourceState, number>; elements: Record<ElementState, number> };
}

// ---------------------------------------------------------------- checking helpers

type Rec = Record<string, unknown>;
type Shown = (Figure | Passage)[];
class Refused extends Error {}

function need(ok: unknown, where: string, rule: string): asserts ok {
  if (!ok) throw new Refused(`${where}: ${rule}`);
}
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;

function rec(value: unknown, keys: readonly string[], where: string): Rec {
  need(isRec(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)),
    where, "does not have exactly the expected fields");
  return value;
}
function text(value: unknown, where: string): string {
  need(isText(value), where, "expected text");
  return value;
}
function oneOf<T extends string>(value: unknown, options: readonly T[], where: string): T {
  need(typeof value === "string" && (options as readonly string[]).includes(value), where,
    `expected one of ${options.join(", ")}`);
  return value as T;
}
function list(value: unknown, where: string, minimum = 0): unknown[] {
  need(Array.isArray(value) && value.length >= minimum, where, `expected a list of at least ${minimum}`);
  return value;
}
function names(value: unknown, where: string, minimum = 0): string[] {
  const values = list(value, where, minimum);
  need(values.every(isText) && new Set(values).size === values.length, where, "expected distinct ids");
  return values as string[];
}
const validDay = (value: string) => {
  const time = Date.parse(`${value}T00:00:00Z`);
  return !Number.isNaN(time) && new Date(time).toISOString().slice(0, 10) === value;
};
function day(value: unknown, where: string): string {
  need(typeof value === "string" && DAY.test(value) && validDay(value), where, "expected a YYYY-MM-DD date");
  return value;
}
/** An https address without credentials or a port, as the server accepts one (thesis_schema._url). */
function httpsAddress(value: unknown): boolean {
  if (typeof value !== "string" || /\s/.test(value) || value.includes("@") || !/^https:\/\//i.test(value)) return false;
  try {
    return new URL(value).hostname !== "" && !value.slice(8).split(/[/?#]/)[0].includes(":");
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- exact decimals (thesisNumbers.ts), as refusals

function decimal(value: unknown, where: string): Dec {
  const exact = plainDecimal(value);
  need(exact !== null, where, "expected a plain decimal written as text");
  return exact;
}
/** A number as the server displays it (comma thousands, exactly `places` decimals, never "-0"), scaled by 10^places. */
function displayed(value: unknown, places: number, where: string): bigint {
  need(typeof value === "string" && displayedPattern(places).test(value), where,
    `expected a number shown to ${places} decimal places`);
  const shown = displayedValue(value);
  need(!(value.startsWith("-") && shown === 0n), where, "expected no negative zero");
  return shown;
}

// ---------------------------------------------------------------- figures, passages and statements

interface Context {
  sources: Map<string, ThesisSource>;
  forms: Map<string, string>;  // Figure or passage id -> how it reads, so it reads the same wherever it is shown.
  items: Map<string, string>;  // Figure or passage id -> its source, across every element.
  own: Set<string>;  // The thesis's own ids: tables, differs, reasons, risks and conditions share one namespace.
  reasons: Set<string>;
  claims: Set<string>;
}
const FIGURE_KEYS = ["id", "value", "as_shown", "unit", "year", "period", "basis", "scenario", "source", "where",
  "measure", "quote"] as const;

function itemSource(ctx: Context, id: string, source: string, where: string): void {
  need(ctx.sources.has(source), where, "names no listed source");
  need((ctx.items.get(id) ?? source) === source, where, "names a different source for this figure or passage");
  ctx.items.set(id, source);
}
function readsSame(ctx: Context, id: string, form: unknown[], where: string): void {
  const read = JSON.stringify(form);
  need((ctx.forms.get(id) ?? read) === read, where, "reads differently where the same figure or passage is shown");
  ctx.forms.set(id, read);
}
/** The place a figure or passage names in its source; a PDF page must be one the source's transcription lists. */
function place(value: unknown, source: ThesisSource, where: string): void {
  const found = WHERE[source.kind].exec(typeof value === "string" ? value : "");
  need(found !== null, where, `expected a place in a ${source.kind} source`);
  need(source.kind !== "pdf" || source.transcription!.pages.includes(Number(found[1])), where,
    "names a page its source's transcription does not list");
}

function figure(value: unknown, where: string, ctx: Context, unit?: Unit): Figure {
  const f = rec(value, FIGURE_KEYS, where);
  const id = text(f.id, `${where}.id`);
  const exact = decimal(f.value, `${where}.value`);
  const asShown = text(f.as_shown, `${where}.as_shown`);
  const print = printed(asShown);
  need(print !== null && sign(difference(print, exact)) === 0, `${where}.as_shown`,
    "does not print the figure's value");
  oneOf(f.unit, UNITS, `${where}.unit`);
  need(unit === undefined || f.unit === unit, `${where}.unit`, `expected a figure in ${unit}`);
  need(f.year === null || (typeof f.year === "string" && YEAR.test(f.year)), `${where}.year`,
    "expected a four-digit year or null");
  need(f.period === null || (typeof f.period === "string" && PERIOD.test(f.period) &&
    f.period.slice(0, 4) === f.year && (f.period.length !== 10 || validDay(f.period))), `${where}.period`,
  "expected null or a period within its year");
  for (const key of ["basis", "scenario"]) {
    need(f[key] === null || isText(f[key]), `${where}.${key}`, "expected text or null");
  }
  text(f.measure, `${where}.measure`);
  itemSource(ctx, id, f.source as string, `${where}.source`);
  const source = ctx.sources.get(f.source as string)!;
  place(f.where, source, `${where}.where`);
  if (source.kind === "html" || source.kind === "pdf") {
    need(isText(f.quote) && f.quote.includes(asShown), `${where}.quote`, "expected the quote that prints the figure");
  } else {
    need(f.quote === null, `${where}.quote`, "only a figure from a page or a PDF carries a quote");
  }
  readsSame(ctx, id, ["figure", ...FIGURE_KEYS.map((key) => f[key])], where);
  return f as unknown as Figure;
}

function passage(value: unknown, where: string, ctx: Context): Passage {
  const p = rec(value, ["id", "source", "quote", "where"], where);
  const id = text(p.id, `${where}.id`);
  text(p.quote, `${where}.quote`);
  itemSource(ctx, id, p.source as string, `${where}.source`);
  const source = ctx.sources.get(p.source as string)!;
  need(source.kind === "html" || source.kind === "pdf", `${where}.source`, "a passage quotes a page or a PDF");
  place(p.where, source, `${where}.where`);
  readsSame(ctx, id, ["passage", p.id, p.source, p.quote, p.where], where);
  return p as unknown as Passage;
}

/** The cited figures and passages, each list in citation order, together exactly the cites: returned in that order. */
function cited(cites: string[], figures: unknown, passages: unknown, where: string, ctx: Context): Shown {
  const shownFigures = list(figures, `${where}.figures`).map((item, i) => figure(item, `${where}.figures[${i}]`, ctx));
  const shownPassages = list(passages, `${where}.passages`)
    .map((item, i) => passage(item, `${where}.passages[${i}]`, ctx));
  const figureIds = shownFigures.map((item) => item.id);
  const passageIds = shownPassages.map((item) => item.id);
  const order = (ids: string[]) => cites.filter((id) => ids.includes(id)).join("\n");
  need(cites.every((id) => figureIds.includes(id) || passageIds.includes(id)) &&
    figureIds.length + passageIds.length === cites.length && order(figureIds) === figureIds.join("\n") &&
    order(passageIds) === passageIds.join("\n"), where, "does not show exactly what it cites, in citation order");
  const byId = new Map<string, Figure | Passage>([...shownFigures, ...shownPassages].map((item) => [item.id, item]));
  return cites.map((id) => byId.get(id)!);
}

function statement(value: unknown, where: string, ctx: Context): Shown {
  const s = rec(value, ["status", "text", "cites", "figures", "passages"], where);
  const status = oneOf(s.status, STATEMENT_STATUSES, `${where}.status`);
  text(s.text, `${where}.text`);
  const cites = names(s.cites, `${where}.cites`);
  need((status === "not_stated") === (cites.length === 0), `${where}.cites`,
    "a statement the sources do not make cites nothing, and any other cites something");
  return cited(cites, s.figures, s.passages, where, ctx);
}

// ---------------------------------------------------------------- elements

const CHECK_KEYS = ["items", "sources", "state", "problems", "not_found"];
interface Shape { frame: readonly string[]; content: readonly string[] }
const SHAPES = {
  view: { frame: ["id"], content: ["statement"] },
  table: { frame: ["id", "title", "gap"], content: ["why_not", "rows"] },
  differs: { frame: ["id"], content: ["about", "others", "differs"] },
  claim: { frame: ["id", "title", "plain"], content: ["statement", "measure", "status", "change_pct", "moved_by"] },
  condition: { frame: ["id"], content: ["threshold_value", "comparator", "text", "figure", "threshold", "status"] },
  mover: { frame: ["id", "company", "moves"], content: ["through", "cites", "figures", "passages"] },
  moved: { frame: ["id", "company", "side"], content: ["how", "amount", "usd_per_unit", "share_pct"] },
  price: { frame: ["id", "series"], content: ["opening", "latest"] },
} satisfies Record<string, Shape>;

/** A title or series: text while the element is available; withheld, null or text without digits (ruling R9). */
function caption(value: unknown, shown: boolean, where: string): void {
  if (shown) text(value, where);
  else need(value === null || (isText(value) && !DIGIT.test(value)), where, "a withheld element shows no digits here");
}
function ownId(e: Rec, where: string, ctx: Context): string {
  need(isText(e.id) && ID.test(e.id) && !ctx.own.has(e.id), `${where}.id`,
    "expected an id distinct among the thesis's own");
  ctx.own.add(e.id);
  return e.id;
}

/** One element of any kind: its frame, its check (items, at least one by ruling R15; sources, state, problems, not
 * found) and, only when it is available, its content, which must show exactly its items in the order it names them. */
function element(value: unknown, section: string, index: number | null, shape: Shape, ctx: Context,
                 frame: (e: Rec, where: string, shown: boolean) => void,
                 content: (e: Rec, where: string) => Shown): Rec {
  const e = rec(value, [...shape.frame, ...CHECK_KEYS, ...shape.content],
    index === null ? section : `${section}[${index}]`);
  const where = index === null ? section : `${section}[${isText(e.id) && ID.test(e.id) ? e.id : index}]`;
  const items = list(e.items, `${where}.items`).map((value, i) => {
    const item = rec(value, ["id", "source"], `${where}.items[${i}]`);
    need(isText(item.id) && isText(item.source), `${where}.items[${i}]`,
      "expected a figure or passage id and its source");
    itemSource(ctx, item.id, item.source, `${where}.items[${i}]`);
    return item as unknown as Item;
  });
  need(items.length > 0, `${where}.items`, "cites no figure or passage, so nothing on it could be checked");
  need(new Set(items.map((item) => item.id)).size === items.length, `${where}.items`, "names one item twice");
  const sources = [...new Set(items.map((item) => item.source))].sort();
  need(Array.isArray(e.sources) && e.sources.length === sources.length && e.sources.every((id, i) => id === sources[i]),
    `${where}.sources`, "expected the sorted ids of its items' sources");
  const notFound = names(e.not_found, `${where}.not_found`);
  const sourceOf = new Map(items.map((item) => [item.id, item.source]));
  need(notFound.every((id, i) => sourceOf.has(id) && (i === 0 || notFound[i - 1] < id)), `${where}.not_found`,
    "expected the sorted ids of its own items");
  need(notFound.every((id) => ctx.sources.get(sourceOf.get(id)!)!.state === "verified"), `${where}.not_found`,
    "names an item whose source was not read");
  const states = sources.map((id) => ctx.sources.get(id)!.state);
  const state = states.includes("missing") ? "unavailable"
    : states.includes("changed") || notFound.length > 0 ? "needs_revalidation" : "available";
  need(e.state === state, `${where}.state`, "does not follow from its sources' states and the items not found");
  const unread = sources.filter((id) => ctx.sources.get(id)!.state !== "verified")
    .map((id) => `${id}: ${ctx.sources.get(id)!.detail}`);
  const unfound = items.filter((item) => notFound.includes(item.id)).map((item) => `${item.id}: `);
  const problems = list(e.problems, `${where}.problems`);
  need(problems.length === unread.length + unfound.length && unread.every((line, i) => problems[i] === line) &&
    unfound.every((prefix, i) => {
      const line = problems[unread.length + i];
      return isText(line) && line.startsWith(prefix) && line.length > prefix.length;
    }), `${where}.problems`, "do not name each source not verified and then each item not found, in order");
  frame(e, where, state === "available");
  if (state !== "available") {
    for (const key of shape.content) need(e[key] === null, `${where}.${key}`, "is shown while the element is withheld");
    return e;
  }
  const used = [...new Map(content(e, where).map((item) => [item.id, item.source])).entries()];
  need(used.length === items.length &&
    used.every(([id, source], i) => items[i].id === id && items[i].source === source),
  `${where}.items`, "are not the figures and passages it shows, in the order it names them");
  return e;
}

function table(e: Rec, where: string, ctx: Context): Shown {
  const computed = e.gap === "computed";
  need(computed ? e.why_not === null : isText(e.why_not), `${where}.why_not`,
    "a computed gap gives no reason for not computing; a table that does not compute one gives a reason");
  const shown: Figure[] = [];
  let previous = "";
  list(e.rows, `${where}.rows`, 1).forEach((value, index) => {
    const at = `${where}.rows[${index}]`;
    const row = rec(value, ["year", "kind", "demand_total", "supply_total", "lines", "gap", "label", "weeks"], at);
    need(typeof row.year === "string" && YEAR.test(row.year) && row.year > previous, `${at}.year`,
      "expected four-digit years that increase");
    previous = row.year;
    oneOf(row.kind, ROW_KINDS, `${at}.kind`);
    const demand = figure(row.demand_total, `${at}.demand_total`, ctx);
    const supply = figure(row.supply_total, `${at}.supply_total`, ctx);
    const lines = list(row.lines, `${at}.lines`).map((line, i) => {
      const item = rec(line, ["label", "figure"], `${at}.lines[${i}]`);
      text(item.label, `${at}.lines[${i}].label`);
      return figure(item.figure, `${at}.lines[${i}].figure`, ctx);
    });
    const figures = [demand, supply, ...lines];
    need(figures.every((item) => item.year === row.year), at, "shows a figure that is not of its year");
    shown.push(...figures);
    if (!computed) {
      for (const key of ["gap", "label", "weeks"]) {
        need(row[key] === null, `${at}.${key}`, "is shown without a computed gap");
      }
      return;
    }
    const total = decimal(demand.value, `${at}.demand_total.value`);
    need(total.n > 0n, `${at}.demand_total`, "expected demand greater than 0");
    const gap = difference(decimal(supply.value, `${at}.supply_total.value`), total);
    need(displayed(row.gap, gap.s, `${at}.gap`) === gap.n, `${at}.gap`, "is not supply less demand");
    need(row.label === (gap.n > 0n ? "surplus" : gap.n < 0n ? "deficit" : "balanced"), `${at}.label`,
      "does not match the sign of the gap");
    // Weeks of demand: |gap| x 52 / demand, rounded half-even to one decimal (ruling R10: the server multiplies first,
    // so an exact half stays exact).
    need(displayed(row.weeks, 1, `${at}.weeks`) === halfEven(abs(gap.n) * 52n, scaled(total, gap.s), 1),
      `${at}.weeks`, "is not the gap in weeks of demand");
  });
  if (computed) {
    for (const key of ["source", "basis", "scenario", "unit"] as const) {
      need(new Set(shown.map((item) => item[key])).size === 1, where,
        `a computed gap draws every figure from one ${key}`);
    }
  }
  return shown;
}

function differs(e: Rec, where: string, ctx: Context): Shown {
  const about = statement(e.about, `${where}.about`, ctx);
  const others = list(e.others, `${where}.others`, 1).map((value, index) => {
    const at = `${where}.others[${index}]`;
    const other = rec(value, ["cite", "label", "figure", "passage"], at);
    text(other.label, `${at}.label`);
    need((other.figure === null) !== (other.passage === null), at, "shows either a figure or a passage");
    const item = other.figure !== null ? figure(other.figure, `${at}.figure`, ctx)
      : passage(other.passage, `${at}.passage`, ctx);
    need(item.id === other.cite, `${at}.cite`, "is not the figure or passage shown");
    return item;
  });
  need(new Set(others.map((item) => item.id)).size === others.length, `${where}.others`, "names one item twice");
  need(typeof e.differs === "boolean", `${where}.differs`, "expected true or false");
  return [...about, ...others];
}

/** Ruling R12: two figures from one source (one edition) compare a later year with an earlier one (period), never one
 * year revised; figures from two sources compare a later edition with an earlier one, one year revised (revision) or a
 * later year (period). Either way they share measure, unit, basis and scenario, and each has a year. */
function compared(latest: Figure, previous: Figure, compare: string, at: string, ctx: Context): void {
  for (const key of ["measure", "unit", "basis", "scenario"] as const) {
    need(latest[key] === previous[key], at, `the latest and previous figures differ in ${key}`);
  }
  need(latest.id !== previous.id, at, "names one figure twice");
  need(latest.year !== null && previous.year !== null, at, "both figures need a year");
  if (latest.source === previous.source) {
    need(compare === "period" && latest.year > previous.year, `${at}.compare`,
      "two figures from one edition compare a later year with an earlier one (period), never one year revised");
    return;
  }
  need(ctx.sources.get(latest.source)!.edition_date > ctx.sources.get(previous.source)!.edition_date, at,
    "the latest figure must come from a later edition than the previous figure");
  need(compare === "revision" ? latest.year === previous.year : latest.year > previous.year, `${at}.compare`,
    "a revision compares one year in two editions; a period comparison a later year in the later edition");
}

/** A reason (supports_when: strengthening / weakening) or a risk (grows_when: materialising / receding; a risk without
 * a measure is not tracked). Statuses are recomputed from the exact values, never from the rounded change_pct. */
function claim(e: Rec, where: string, ctx: Context, isRisk: boolean): Shown {
  const shown = statement(e.statement, `${where}.statement`, ctx);
  if (e.measure === null) {
    need(isRisk, `${where}.measure`, "a reason has a measure");
    need(e.status === "not_tracked", `${where}.status`, "a risk without a measure is not tracked");
    need(e.change_pct === null && e.moved_by === null, `${where}.change_pct`,
      "a risk without a measure shows no change");
    return shown;
  }
  const direction = isRisk ? "grows_when" : "supports_when";
  const at = `${where}.measure`;
  const m = rec(e.measure, ["latest", "previous", "compare", direction, "material_change_pct"], at);
  const latest = figure(m.latest, `${at}.latest`, ctx);
  const previous = figure(m.previous, `${at}.previous`, ctx);
  compared(latest, previous, oneOf(m.compare, COMPARES, `${at}.compare`), at, ctx);
  const wanted = oneOf(m[direction], DIRECTIONS, `${at}.${direction}`);
  const material = decimal(m.material_change_pct, `${at}.material_change_pct`);
  need(material.n > 0n, `${at}.material_change_pct`, "expected a material change greater than 0");
  const before = decimal(previous.value, `${at}.previous.value`);
  need(before.n !== 0n, `${at}.previous`, "a previous value of zero has no change in percent");
  const change = difference(decimal(latest.value, `${at}.latest.value`), before);
  const base = abs(scaled(before, change.s));
  // unchanged exactly when |latest - previous| / |previous| x 100 < material, in integers.
  const unchanged = abs(change.n) * 100n * pow10(material.s) < material.n * base;
  const [toward, away] = isRisk ? ["materialising", "receding"] : ["strengthening", "weakening"];
  need(e.status === (unchanged ? "unchanged" : (change.n > 0n ? "higher" : "lower") === wanted ? toward : away),
    `${where}.status`, "does not follow from the exact latest and previous values and the material change");
  need(displayed(e.change_pct, 1, `${where}.change_pct`) === halfEven(change.n * 100n, base, 1),
    `${where}.change_pct`, "is not the change from the previous value in percent");
  const by = rec(e.moved_by, ["source", "publisher", "edition", "edition_date"], `${where}.moved_by`);
  const origin = ctx.sources.get(latest.source)!;
  need(by.source === origin.id && by.publisher === origin.publisher && by.edition === origin.edition &&
    by.edition_date === origin.edition_date, `${where}.moved_by`, "is not the source of the latest figure");
  return [...shown, latest, previous];
}

/** A condition; its threshold, as written and as shown, is content, withheld with it (final review M4). */
function condition(e: Rec, where: string, ctx: Context): Shown {
  const comparator = oneOf(e.comparator, COMPARATORS, `${where}.comparator`);
  text(e.text, `${where}.text`);
  const shown = figure(e.figure, `${where}.figure`, ctx);
  const threshold = decimal(e.threshold_value, `${where}.threshold_value`);
  need(displayed(e.threshold, threshold.s, `${where}.threshold`) === threshold.n, `${where}.threshold`,
    "is not the threshold as written");
  const order = sign(difference(decimal(shown.value, `${where}.figure.value`), threshold));
  need(e.status === ((comparator === "below" ? order < 0 : order > 0) ? "happened" : "not_happened"),
    `${where}.status`, "does not follow from the figure and the threshold (a figure equal to it is not past it)");
  return [shown];
}

function moved(e: Rec, where: string, ctx: Context): Shown {
  const how = statement(e.how, `${where}.how`, ctx);
  const at = `${where}.amount`;
  if (isRec(e.amount) && e.amount.kind === "stated") {
    const amount = rec(e.amount, ["kind", "figure"], at);
    need(e.usd_per_unit === null, `${where}.usd_per_unit`, "a stated amount computes nothing");
    need(e.share_pct === null, `${where}.share_pct`, "a stated amount computes nothing");
    return [...how, figure(amount.figure, `${at}.figure`, ctx)];
  }
  const amount = rec(e.amount, ["kind", "per_unit", "price", "unit_price"], at);
  need(amount.kind === "computed", `${at}.kind`, "expected stated or computed");
  const perUnit = figure(amount.per_unit, `${at}.per_unit`, ctx, "kg_per_unit");
  const price = figure(amount.price, `${at}.price`, ctx, "usd_per_tonne");
  const kg = decimal(perUnit.value, `${at}.per_unit.value`);
  const usd = decimal(price.value, `${at}.price.value`);
  need(kg.n > 0n && usd.n > 0n, at, "expected an amount per unit and a price greater than 0");
  // Whole dollars per unit: kilograms per unit x US dollars per tonne / 1000.
  const cost = displayed(e.usd_per_unit, 0, `${where}.usd_per_unit`);
  need(cost === halfEven(kg.n * usd.n, pow10(kg.s + usd.s) * 1000n, 0), `${where}.usd_per_unit`,
    "is not the amount per unit times the price per tonne");
  if (amount.unit_price === null) {
    need(e.share_pct === null, `${where}.share_pct`, "a share needs a unit price");
    return [...how, perUnit, price];
  }
  const unitPrice = figure(amount.unit_price, `${at}.unit_price`, ctx, "usd");
  const whole = decimal(unitPrice.value, `${at}.unit_price.value`);
  need(whole.n > 0n, `${at}.unit_price`, "expected a unit price greater than 0");
  // The share is of the whole-dollar cost as displayed, to one decimal (thesis_sections).
  need(displayed(e.share_pct, 1, `${where}.share_pct`) === halfEven(cost * 100n * pow10(whole.s), whole.n, 1),
    `${where}.share_pct`, "is not the whole-dollar cost as a share of the unit price");
  return [...how, perUnit, price, unitPrice];
}

// ---------------------------------------------------------------- the reply

function source(value: unknown, index: number, ctx: Context): ThesisSource {
  const s = rec(value, ["id", "publisher", "title", "edition", "edition_date", "url", "kind", "origin", "terms",
    "transcription", "retrieved_at", "sha256", "state", "detail"], `sources[${index}]`);
  need(isText(s.id) && ID.test(s.id), `sources[${index}].id`, "expected a lower-case id");
  const where = `sources[${s.id}]`;
  need(!ctx.sources.has(s.id), `${where}.id`, "is listed twice");
  for (const key of ["publisher", "title", "edition", "detail"]) text(s[key], `${where}.${key}`);
  day(s.edition_date, `${where}.edition_date`);
  need(httpsAddress(s.url), `${where}.url`, "expected an https address without credentials or a port");
  const kind = oneOf(s.kind, KINDS, `${where}.kind`);
  oneOf(s.origin, ORIGINS, `${where}.origin`);
  const terms = rec(s.terms, ["licence", "note"], `${where}.terms`);
  text(terms.licence, `${where}.terms.licence`);
  text(terms.note, `${where}.terms.note`);
  if (kind === "pdf") {
    const transcription = rec(s.transcription, ["pages", "method"], `${where}.transcription`);
    const pages = list(transcription.pages, `${where}.transcription.pages`, 1);
    need(pages.every((page, i) => Number.isInteger(page) && (page as number) >= 1 &&
      (i === 0 || (page as number) > (pages[i - 1] as number))), `${where}.transcription.pages`,
    "expected whole page numbers of at least 1, ascending, each once");
    need((TRANSCRIPTION_METHODS as readonly unknown[]).includes(transcription.method),
      `${where}.transcription.method`, `expected one of ${JSON.stringify(TRANSCRIPTION_METHODS)}`);
  } else {
    need(s.transcription === null, `${where}.transcription`, "only a PDF is transcribed");
  }
  need(isText(s.retrieved_at) && !Number.isNaN(Date.parse(s.retrieved_at)), `${where}.retrieved_at`,
    "expected a time");
  need(typeof s.sha256 === "string" && SHA.test(s.sha256), `${where}.sha256`, "expected a SHA-256");
  oneOf(s.state, SOURCE_STATES, `${where}.state`);
  ctx.sources.set(s.id, s as unknown as ThesisSource);
  return s as unknown as ThesisSource;
}

function versions(v: Rec, id: string, version: number | null): void {
  const entries = list(v.versions, "versions", 1).map((value, index) => {
    const entry = rec(value, ["version", "published_on"], `versions[${index}]`);
    need(entry.version === index + 1, `versions[${index}].version`, "expected versions numbered 1, 2, … in order");
    return entry;
  });
  entries.forEach((entry, index) => {
    const before = index > 0 ? entries[index - 1].published_on as string : null;  // Not null: only the last may be.
    need(entry.published_on === null ? index === entries.length - 1 : typeof entry.published_on === "string" &&
      DAY.test(entry.published_on) && validDay(entry.published_on) &&
      (before === null || before <= entry.published_on), `versions[${index}].published_on`,
    "only the last version may be a draft, and publication dates do not decrease");
  });
  need(v.id === id && ID.test(id), "id", "is not the thesis asked for");
  need(Number.isInteger(v.version) && (version === null ? v.version === entries.length : v.version === version) &&
    (v.version as number) >= 1 && (v.version as number) <= entries.length, "version", "is not the version asked for");
  need(v.published_on === entries[(v.version as number) - 1].published_on, "published_on",
    "is not the date its version is listed with");
  need(v.draft === (v.published_on === null), "draft", "a version is a draft exactly when it is not published");
  const opened = day(v.opened_on, "opened_on");
  const prepared = day(v.prepared_on, "prepared_on");
  need(opened <= prepared, "prepared_on", "is before the thesis opened");
  need(v.published_on === null || (v.published_on as string) >= prepared, "published_on",
    "is before the version was prepared");
}

const TOP_KEYS = ["view_version", "thesis_version", "id", "version", "versions", "draft", "title", "topic", "opened_on",
  "prepared_on", "published_on", "confidence", "provider_called", "labels", "sources", "view", "balance", "differs",
  "reasons", "risks", "conditions", "exposure", "price_record", "log", "plain", "not_claimed", "provenance", "counts"];

function check(body: unknown, id: string, version: number | null): void {
  const v = rec(body, TOP_KEYS, "reply");
  need(v.view_version === THESIS_VIEW_VERSION, "view_version", `expected ${THESIS_VIEW_VERSION}`);
  need(v.thesis_version === THESIS_VERSION, "thesis_version", `expected ${THESIS_VERSION}`);
  need(v.provider_called === false, "provider_called", "expected false: a read calls nothing");
  versions(v, id, version);
  text(v.title, "title");
  text(v.topic, "topic");
  const confidence = rec(v.confidence, ["level", "basis"], "confidence");
  oneOf(confidence.level, CONFIDENCE_LEVELS, "confidence.level");
  text(confidence.basis, "confidence.basis");
  const labels = rec(v.labels, Object.keys(LABEL_GROUPS), "labels");
  for (const [group, keys] of Object.entries(LABEL_GROUPS)) {
    const named = rec(labels[group], keys, `labels.${group}`);
    for (const key of keys) text(named[key], `labels.${group}.${key}`);
  }
  const ctx: Context = { sources: new Map(), forms: new Map(), items: new Map(), own: new Set(), reasons: new Set(),
    claims: new Set() };
  const sources = list(v.sources, "sources", 1).map((value, index) => source(value, index, ctx));
  const every: Rec[] = [];
  const add = (...values: Rec[]) => every.push(...values);
  add(element(v.view, "view", null, SHAPES.view, ctx, (e, where) => {
    need(e.id === VIEW_ID, `${where}.id`, `expected "${VIEW_ID}"`);
  }, (e, where) => statement(e.statement, `${where}.statement`, ctx)));
  const balance = rec(v.balance, ["tables"], "balance");
  add(...list(balance.tables, "balance.tables", 1).map((value, index) =>
    element(value, "balance.tables", index, SHAPES.table, ctx, (e, where, shown) => {
      ownId(e, where, ctx);
      oneOf(e.gap, GAPS, `${where}.gap`);
      caption(e.title, shown, `${where}.title`);
    }, (e, where) => table(e, where, ctx))));
  add(...list(v.differs, "differs", 1).map((value, index) => element(value, "differs", index, SHAPES.differs, ctx,
    (e, where) => { ownId(e, where, ctx); }, (e, where) => differs(e, where, ctx))));
  for (const [section, isRisk] of [["reasons", false], ["risks", true]] as const) {
    add(...list(v[section], section, 1).map((value, index) => element(value, section, index, SHAPES.claim, ctx,
      (e, where, shown) => {
        const name = ownId(e, where, ctx);
        if (!isRisk) ctx.reasons.add(name);
        ctx.claims.add(name);
        caption(e.title, shown, `${where}.title`);
        text(e.plain, `${where}.plain`);
      }, (e, where) => claim(e, where, ctx, isRisk))));
  }
  add(...list(v.conditions, "conditions", 1).map((value, index) => element(value, "conditions", index,
    SHAPES.condition, ctx, (e, where) => { ownId(e, where, ctx); }, (e, where) => condition(e, where, ctx))));
  const exposure = rec(v.exposure, ["movers", "moved"], "exposure");
  add(...list(exposure.movers, "exposure.movers", 1).map((value, index) => element(value, "exposure.movers", index,
    SHAPES.mover, ctx, (e, where) => {
      need(e.id === `mover-${index + 1}`, `${where}.id`, "expected movers numbered mover-1, mover-2, … in order");
      text(e.company, `${where}.company`);
      need(typeof e.moves === "string" && ctx.reasons.has(e.moves), `${where}.moves`, "names no reason");
    }, (e, where) => {
      text(e.through, `${where}.through`);
      return cited(names(e.cites, `${where}.cites`, 1), e.figures, e.passages, where, ctx);
    })));
  add(...list(exposure.moved, "exposure.moved", 1).map((value, index) => element(value, "exposure.moved", index,
    SHAPES.moved, ctx, (e, where) => {
      need(e.id === `moved-${index + 1}`, `${where}.id`, "expected entries numbered moved-1, moved-2, … in order");
      text(e.company, `${where}.company`);
      oneOf(e.side, SIDES, `${where}.side`);
    }, (e, where) => moved(e, where, ctx))));
  add(element(v.price_record, "price_record", null, SHAPES.price, ctx, (e, where, shown) => {
    need(e.id === PRICE_RECORD_ID, `${where}.id`, `expected "${PRICE_RECORD_ID}"`);
    caption(e.series, shown, `${where}.series`);
  }, (e, where) => {
    const opening = figure(e.opening, `${where}.opening`, ctx), latest = figure(e.latest, `${where}.latest`, ctx);
    for (const [name, found] of [["opening", opening], ["latest", latest]] as const)
      need((PRICE_UNITS as readonly string[]).includes(found.unit), `${where}.${name}`, `expected one of ${PRICE_UNITS}`);
    need(opening.unit === latest.unit, where, `the opening is in ${opening.unit}, the latest in ${latest.unit}`);
    return [opening, latest];
  }));
  let last = "";
  list(v.log, "log", 1).forEach((value, index) => {
    const where = `log[${index}]`;
    const entry = rec(value, ["date", "kind", "text", "refs"], where);
    const date = day(entry.date, `${where}.date`);
    need(date >= last && date <= (v.prepared_on as string), `${where}.date`,
      "expected dates that do not decrease, none after the version was prepared");
    last = date;
    const kind = oneOf(entry.kind, LOG_KINDS, `${where}.kind`);
    need((kind === "opened") === (index === 0), `${where}.kind`, "the first entry, and only the first, is the opening");
    text(entry.text, `${where}.text`);
    const refs = names(entry.refs, `${where}.refs`, kind === "status" ? 1 : 0);
    need(refs.every((ref) => ctx.claims.has(ref)), `${where}.refs`, "expected ids of this version's reasons or risks");
  });
  const plain = rec(v.plain, PLAIN_KEYS, "plain");
  for (const key of PLAIN_KEYS) text(plain[key], `plain.${key}`);
  need(list(v.not_claimed, "not_claimed", 1).every(isText), "not_claimed", "expected texts");
  const provenance = rec(v.provenance, ["prepared_by", "method", "ai_assisted", "human_review", "research_use"],
    "provenance");
  need(isText(provenance.prepared_by) && isText(provenance.method) && provenance.ai_assisted === true &&
    provenance.human_review === "not_reviewed" && provenance.research_use === "excluded", "provenance",
  "expected AI-assisted, not reviewed and excluded from research use");
  const counts = rec(v.counts, ["sources", "elements"], "counts");
  const tallied = (value: unknown, states: readonly string[], of: readonly { state?: unknown }[], where: string) => {
    const named = rec(value, states, where);
    need(states.every((state) => named[state] === of.filter((item) => item.state === state).length), where,
      "do not reconcile with the states");
  };
  tallied(counts.sources, SOURCE_STATES, sources, "counts.sources");
  tallied(counts.elements, ELEMENT_STATES, every, "counts.elements");
}

/** Why the reply cannot be read ("<place>: <rule>"), or null when it is the thesis and version asked for (null: the
 * latest) and every state, number and count holds together. Never throws. */
export function thesisRefusal(body: unknown, id: string, version: number | null): string | null {
  try {
    check(body, id, version);
    return null;
  } catch (error) {
    if (error instanceof Refused) return error.message;
    return `reply: could not be read (${error instanceof Error ? error.name : "unknown error"})`;
  }
}

export function isThesisView(body: unknown, id: string, version: number | null): body is ThesisView {
  return thesisRefusal(body, id, version) === null;
}

/** "/theses/copper", or "/theses/copper/versions/2" for one named version. */
export const thesisHref = (id: string, version: number | null) =>
  `/theses/${encodeURIComponent(id)}${version === null ? "" : `/versions/${version}`}`;

export async function fetchThesis(id: string, version: number | null,
                                  signal: AbortSignal): Promise<Loaded<ThesisView>> {
  if (version !== null && !VERSION_NUMBER.test(String(version))) return { state: "missing", message: NO_VERSION };
  let response: Response;
  try {
    response = await fetch(`/api${thesisHref(id, version)}`, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = isRec(body) && typeof body.detail === "string" ? body.detail
    : `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  const refusal = thesisRefusal(body, id, version);
  return refusal === null ? { state: "ready", data: body as ThesisView }
    : { state: "error", message: `The reply could not be read by this page (${refusal}).` };
}

// ---------------------------------------------------------------- reading aids

/** Every element in reply order: the view, the balance tables, differs, reasons, risks, conditions, the companies that
 * move the thesis and those it moves, and the price record. */
export const elementsOf = (view: ThesisView): ThesisElement[] => [view.view, ...view.balance.tables,
  ...view.differs, ...view.reasons, ...view.risks, ...view.conditions, ...view.exposure.movers,
  ...view.exposure.moved, view.price_record];

/** "16 Nov 2026" for a YYYY-MM-DD day. */
export const dayText = (value: string) => formatDay(`${value}T00:00:00Z`);

/** A figure's period as a reader says it ("Oct 2026", "Q3 2026", "15 Oct 2026"), else its year, else "". */
export function periodText(figure: Pick<Figure, "year" | "period">): string {
  const period = figure.period;
  if (period === null) return figure.year ?? "";
  const year = Number(period.slice(0, 4));
  if (period[4] === "M") return monthLabel(Date.UTC(year, Number(period.slice(5)) - 1, 1), true);
  if (period[4] === "Q") return `${period.slice(4)} ${year}`;
  return dayText(period);
}

const UNIT_TEXT: Record<Unit, string> = { kt: "kt", million_t: "million t", t: "t", kg: "kg",
  kg_per_unit: "kg per unit", usd_per_tonne: "USD per tonne", usd_per_lb: "USD per lb",
  usd_cents_per_lb: "US cents per pound", usd: "USD",
  usd_million: "USD million", percent: "percent", count: "" };

/** "22,900 kt · Synthetic USGS 2026 · 2024": a figure as its source prints it, with its unit, its source by publisher
 * and edition (required, so a raw source id is never reader text) and its period or year. A printed "$" or "%" already
 * names the unit. */
export function figureText(figure: Figure, source: Pick<ThesisSource, "publisher" | "edition">): string {
  let unit = UNIT_TEXT[figure.unit];
  if (figure.as_shown.startsWith("$")) unit = unit.replace(/^USD ?/, "");
  if (figure.as_shown.endsWith("%") && figure.unit === "percent") unit = "";
  return [unit ? `${figure.as_shown} ${unit}` : figure.as_shown, `${source.publisher} ${source.edition}`,
    periodText(figure)].filter((part) => part !== "").join(" · ");
}

/** "transcribed from the page image (pages 1, 2 of the PDF)": the method used, verbatim (R17), else null. */
export function transcriptionText(source: Pick<ThesisSource, "transcription">): string | null {
  const t = source.transcription, s = t && t.pages.length > 1 ? "s" : "";
  return t ? `${t.method} (page${s} ${t.pages.join(", ")} of the PDF)` : null;
}

// The FCX company page's reader (GET /api/companies/fcx, second_order/company_research_view.py). Fail-closed: a reply
// is shown only after every published figure reads as its printed form, every computed figure recomputes exactly from
// its inputs (BigInt fractions, ROUND_HALF_EVEN at its stated places, as the server's Decimal rounding), every mix of
// bases, periods or units is stated, nothing withheld carries a value, and every text names only known records and
// shows no typed number. A refusal names its place, never a value.
import type { Loaded } from "./api";
import { add, div, equal, halfEven, int, mul, neg, ofPlain, sub, type Rat } from "./copperNumbers.ts";
import { scenarioPageRefusal } from "./companyScenarios.ts";

export const COMPANY_VIEW_VERSION = "company-research-0.2";
export const SOURCE_STATES = ["verified", "missing", "changed"] as const;
const UNREACHABLE = "The local server could not be reached.";

export type SourceState = (typeof SOURCE_STATES)[number];
export interface Source {
  id: string; title: string; issuer: string; form: string; period_end: string; date: string; date_kind: string;
  url: string; host: string; format: string; bytes: number; sha256: string; retrieved_at: string; acquisition: string;
  terms: string; state: SourceState; detail: string;
}
export interface Period { kind: string; label: string; start?: string; end: string }
interface Base { id: string; state: "available" | "withheld"; problem: string | null }
export interface Published extends Base {
  kind: "published"; metric: string; unit: string; period: Period; basis: string; source: string; page: number;
  printed_page?: string; location?: string; row?: string; column?: string; note?: string;
  value: string | null; display: string | null; quote: string | null;
}
export interface Computed extends Base {
  kind: "computed"; metric: string; unit: string; period: Period; basis: string; formula: string;
  inputs: Record<string, string>; decimals: number; note?: string; basis_mix?: string; period_mix?: string;
  unit_mix?: string; assumptions?: string[]; value: string | null;
}
/** An assumption; its statement is null (withheld) when a document it describes is not verified. */
export interface Assumption extends Base { kind: "assumption"; statement: string | null; used_by: string[];
  rests_on: string[] }
export type FigureRecord = Published | Computed;
export type AnyRecord = FigureRecord | Assumption;
export interface Passage extends Base {
  source: string; page: number; printed_page?: string; location?: string; topic?: string; quote: string | null;
}
export type Segment = { text: string } | { ref: string; mode: "signed" | "size" | null };
export type BlockKind = "observation" | "computed" | "estimate" | "company_reason" | "reading" | "note";
/** A text block: its words in segments, or, withheld, no words at all (segments null): only what it names (refs). */
export interface Block { kind: BlockKind; segments: Segment[] | null; refs: string[]; passages: string[];
  state: "available" | "withheld"; problem: string | null }
export interface Tile { id: string; label: string; value: string; compare: string; compare_label: string;
  note_label?: string; note?: Block }
export interface Change extends Block { id: string; detail: Block[] }
export interface Row { label: string; ids: (string | null)[]; note?: Block }
export interface Table { title: string; columns: string[]; rows: Row[] }
export interface NumbersView { id: string; label: string; main: Table; more: Table[] }
export interface Asset { name: string; place: string; what: string; record: string | null; reported: string }
export interface BusinessSection { id: string; title: string; teaser?: string; open?: string; blocks: Block[];
  assets?: Asset[] }
export interface Step { id: string; title: string; link: "stated" | "conditional" | "not_measured"; blocks: Block[] }
export interface Sensitivity { id: string; record: string; measure: string; period_text: string; effect_on: string;
  passages?: string[] }
export interface Labelled { label: string; record: string }
export interface Bagdad {
  decided: Block[]; estimates: Labelled[]; estimate_notes: Block[]; computed: Labelled[]; history: Block[];
  change_columns: string[]; change_rows: Row[]; change_note: Block;
}
export interface QuestionGroup { id: string; title: string; items: Block[] }
/** A company assumption a calculation starts from (its record), with its label. */
export interface ScenarioBase { label: string; record: string }
/** The Scenarios tab's texts (stage 2): each calculation's base records and the explanations, withheld with them. */
export interface Scenarios {
  intro: Block;
  price_volume: { title: string; short: string; base: ScenarioBase[]; base_value: ScenarioBase; definition: Block;
    method: Block[]; sources: Block[]; costs: Block[] };
  cash_flow: { title: string; short: string; base: ScenarioBase[]; definition: Block; linear: Block; held: Block;
    not_used: Block[]; versus: Block };
}
export interface CompanyPage {
  company: { name: string; short: string; kicker: string }; question: string; figures_to: string;
  review: { author: string; state: string }; summary: Block[]; summary_more: Block[]; tiles: Tile[];
  changes: Change[];
  reading_guide: Block[]; business: BusinessSection[];
  numbers: { views: NumbersView[]; dated: Table[]; difference: Block[] };
  mechanisms: { steps: Step[]; sensitivities: Sensitivity[]; sensitivity_note: Block; bagdad: Bagdad };
  scenarios: Scenarios; questions: QuestionGroup[]; method: { checks: Block[]; not_doing: Block[] };
}
export interface RefusedRequest { approval_id: string; n: number; url: string; outcome: string; http_status: number | null }
export interface CompanyView {
  view_version: string; provider_called: false; sources: Source[]; verified: number; requests: RefusedRequest[];
  records: Record<string, AnyRecord>; passages: Record<string, Passage>; page: CompanyPage;
}

const isRec = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value !== "";
const PRINTED = /^(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?$/;
/** Digits a page text may hold: years and the names of SEC forms (the server's rule). */
const ALLOWED_DIGITS = /\b(?:19|20)\d{2}\b|\b(?:10-K|10-Q|8-K)\b/g;
export const typedNumber = (text: string) => /\d/.test(text.replace(ALLOWED_DIGITS, ""));

/** A figure as the records print it: "7,546", "(1,061)", "20%", "0.43%" or "—" (zero), as a fraction; else null. */
export function printedRat(display: string): Rat | null {
  if (display === "—") return int(0);
  const negative = display.startsWith("(") && display.endsWith(")");
  const inner = negative ? display.slice(1, -1) : display;
  const body = inner.endsWith("%") ? inner.slice(0, -1) : inner;
  if (!PRINTED.test(body)) return null;
  const value = ofPlain(body.replace(/,/g, ""));
  return value === null ? null : negative ? neg(value) : value;
}

// ---------------------------------------------------------------- exact formulas

type Token = { kind: "num" | "name" | "op"; text: string };
function tokens(formula: string): Token[] | null {
  const out: Token[] = [];
  const pattern = /\s*(?:(\d+(?:\.\d+)?)|([a-z_][a-z0-9_]*)|([-+*/()]))/y;
  let at = 0;
  while (at < formula.length) {
    if (/^\s+$/.test(formula.slice(at))) break;
    pattern.lastIndex = at;
    const match = pattern.exec(formula);
    if (!match) return null;
    out.push(match[1] ? { kind: "num", text: match[1] } : match[2] ? { kind: "name", text: match[2] }
      : { kind: "op", text: match[3] });
    at = pattern.lastIndex;
  }
  return out;
}

/** + - * / and parentheses over named inputs and numbers, as exact fractions; null for anything else. */
export function evaluate(formula: string, values: Record<string, Rat>): Rat | null {
  const list = tokens(formula);
  if (list === null) return null;
  let at = 0;
  const peek = () => list[at]?.text;
  const fail = Symbol("fail");
  const primary = (): Rat => {
    const token = list[at++];
    if (!token) throw fail;
    if (token.kind === "num") return ofPlain(token.text) ?? (() => { throw fail; })();
    if (token.kind === "name") { if (!(token.text in values)) throw fail; return values[token.text]; }
    if (token.text === "-") return neg(primary());
    if (token.text === "(") { const inner = sum(); if (list[at++]?.text !== ")") throw fail; return inner; }
    throw fail;
  };
  const product = (): Rat => {
    let left = primary();
    while (peek() === "*" || peek() === "/") {
      const op = list[at++].text;
      const right = primary();
      if (op === "/" && right.n === 0n) throw fail;
      left = op === "*" ? mul(left, right) : div(left, right);
    }
    return left;
  };
  const sum = (): Rat => {
    let left = product();
    while (peek() === "+" || peek() === "-") {
      const op = list[at++].text;
      const right = product();
      left = op === "+" ? add(left, right) : sub(left, right);
    }
    return left;
  };
  try {
    const result = sum();
    return at === list.length ? result : null;
  } catch (error) {
    if (error === fail) return null;
    throw error;
  }
}

// ---------------------------------------------------------------- the reader

const PERIOD_KINDS = ["quarter", "half_year", "nine_months", "year", "as_of", "outlook"];
/** All a withheld figure may carry: what it is, where it would come from and why it is not shown (the server's
 * IDENTIFYING). A note, an explanation, a row or column label, a quote or a value is refused. */
const WITHHELD_FIELDS: Record<string, Set<string>> = {
  published: new Set(["id", "kind", "metric", "unit", "period", "basis", "source", "page", "printed_page", "location",
    "rests_on", "state", "problem", "value", "display", "quote"]),
  computed: new Set(["id", "kind", "metric", "unit", "period", "basis", "formula", "inputs", "decimals", "assumptions",
    "rests_on", "state", "problem", "value"]),
};
/** What names a figure is shown even when it is withheld (and the page builds each figure's accessible label from it),
 * so it carries no percentage: a share or rate from a document is a figure of its own record. */
const PERCENT = /\d\s*%/;
const BLOCK_KINDS: BlockKind[] = ["observation", "computed", "estimate", "company_reason", "reading", "note"];

/** Why a reply cannot be shown, naming the place; null when every check passes. */
export function companyRefusal(body: unknown): string | null {
  if (!isRec(body)) return "the reply is not an object";
  if (body.view_version !== COMPANY_VIEW_VERSION) return "view_version is not the version this page reads";
  if (body.provider_called !== false) return "provider_called is not false";
  if (!Array.isArray(body.sources) || body.sources.length !== 4) return "sources: expected the four documents";
  const sources = new Map<string, Source>();
  for (const [at, source] of body.sources.entries()) {
    if (!isRec(source) || !isText(source.id) || !isText(source.title) || !isText(source.detail)
      || !SOURCE_STATES.includes(source.state as SourceState) || !/^[0-9a-f]{64}$/.test(String(source.sha256))
      || !isText(source.date) || !isText(source.date_kind)) return `sources[${at}]: not a source entry`;
    sources.set(source.id, source as unknown as Source);
  }
  const verified = [...sources.values()].filter((s) => s.state === "verified").length;
  if (body.verified !== verified) return "verified does not count the verified sources";
  if (!isRec(body.records) || !isRec(body.passages) || !isRec(body.page)) return "records, passages or page missing";
  const records = body.records as Record<string, unknown>;
  const passages = body.passages as Record<string, unknown>;
  for (const [id, value] of Object.entries(records)) {
    const problem = recordRefusal(id, value, records, sources);
    if (problem) return `records.${id}: ${problem}`;
  }
  for (const [id, value] of Object.entries(passages)) {
    if (!isRec(value) || value.id !== id || !sources.has(String(value.source))) return `passages.${id}: not a passage`;
    const open = sources.get(String(value.source))!.state === "verified";
    if (value.state === "available" && (!open || !isText(value.quote))) return `passages.${id}: shown without its source`;
    if (value.state !== "available" && value.quote !== null) return `passages.${id}: withheld but carries its quote`;
  }
  return pageRefusal(body.page, records, passages) ?? scenarioPageRefusal(body.page as Record<string, unknown>);
}

function recordRefusal(id: string, value: unknown, records: Record<string, unknown>, sources: Map<string, Source>):
  string | null {
  if (!isRec(value) || value.id !== id) return "not a record";
  if (value.state !== "available" && value.state !== "withheld") return "no state";
  if (value.kind === "assumption") {
    if (value.state === "withheld") return value.statement === null && isText(value.problem) ? null
      : "a withheld assumption carries its statement";
    return isText(value.statement) ? null : "an assumption without its statement";
  }
  const period = value.period;
  if (!isRec(period) || !isText(period.label) || !isText(period.end) || !PERIOD_KINDS.includes(String(period.kind))) {
    return "no period";
  }
  if (!isText(value.unit) || !isText(value.basis) || !isText(value.metric)) return "no unit, basis or metric";
  const named: [string, unknown][] = [["metric", value.metric], ["unit", value.unit], ["basis", value.basis],
    ["location", value.location], ["period label", period.label]];
  for (const [field, text] of named) {
    if (typeof text === "string" && PERCENT.test(text)) return `its ${field} carries a percentage`;  // never the text
  }
  if (value.state === "withheld") {
    const allowed = WITHHELD_FIELDS[String(value.kind)];
    const extra = allowed ? Object.keys(value).filter((key) => !allowed.has(key)) : ["kind"];
    if (extra.length > 0) return `withheld but carries ${extra.join(", ")}`;  // names the fields, never their text
    if (value.value !== null || (value.kind === "published" && (value.display !== null || value.quote !== null))) {
      return "withheld but carries a value";
    }
    return isText(value.problem) ? null : "withheld without a reason";
  }
  if (value.kind === "published") {
    const source = sources.get(String(value.source));
    if (!source) return "an unknown source";
    if (source.state !== "verified") return "shown though its source is not verified";
    if (typeof value.page !== "number" || !isText(value.quote) || !isText(value.display)) return "no page, quote or figure";
    const shown = printedRat(String(value.display));
    const exact = ofPlain(value.value);
    if (shown === null || exact === null || !equal(shown, exact)) return "its printed figure does not read as its value";
    return null;
  }
  if (value.kind !== "computed") return "an unknown kind";
  if (!isText(value.formula) || !isRec(value.inputs) || typeof value.decimals !== "number" || value.decimals < 0) {
    return "no formula, inputs or places";
  }
  const inputs: Record<string, Rat> = {};
  const used: Record<string, unknown>[] = [];
  for (const [name, ref] of Object.entries(value.inputs)) {
    const input = records[String(ref)];
    if (!isRec(input)) return `input ${name} names a record that is not in the reply`;
    if (input.state !== "available") return `input ${name} is withheld`;
    const exact = ofPlain(input.value);
    if (exact === null) return `input ${name} has no exact value`;
    inputs[name] = exact;
    used.push(input);
  }
  const result = evaluate(String(value.formula), inputs);
  const stated = ofPlain(value.value);
  if (result === null || stated === null) return "the formula cannot be evaluated";
  if (halfEven(result, value.decimals) !== halfEven(stated, value.decimals)) return "it does not recompute from its inputs";
  const differ = (key: string) => new Set(used.map((input) => key === "period" ? (input.period as Period).label
    : String(input[key]))).size > 1;
  if (differ("basis") && !isText(value.basis_mix)) return "it mixes bases without saying why";
  if (differ("period") && !isText(value.period_mix)) return "it mixes periods without saying why";
  if (differ("unit") && !isText(value.unit_mix)) return "it mixes units without saying why";
  return null;
}

function pageRefusal(page: unknown, records: Record<string, unknown>, passages: Record<string, unknown>):
  string | null {
  const known = (id: unknown) => typeof id === "string" && id in records;
  const shownRecord = (id: string) => (records[id] as Record<string, unknown>).state === "available";
  const walk = (node: unknown, where: string): string | null => {
    if (Array.isArray(node)) {
      for (const [at, item] of node.entries()) {
        const problem = walk(item, `${where}[${at}]`);
        if (problem) return problem;
      }
      return null;
    }
    if (!isRec(node)) return null;
    if ("segments" in node) {
      if (!BLOCK_KINDS.includes(node.kind as BlockKind) || !Array.isArray(node.refs)) return `${where}: not a block`;
      const refs = node.refs.map(String);
      if (!refs.every(known)) return `${where}: names a record that is not in the reply`;
      if (node.state === "withheld") {
        if (node.segments !== null) return `${where}: withheld but carries its words`;
      } else {
        if (!Array.isArray(node.segments)) return `${where}: not a block`;
        const named: string[] = [];
        for (const segment of node.segments) {
          if (isRec(segment) && "ref" in segment) named.push(String(segment.ref));
          else if (isRec(segment) && typeof segment.text === "string") {
            if (typedNumber(segment.text)) return `${where}: a number is typed in the text`;
          } else return `${where}: not a segment`;
        }
        if (named.join(" ") !== refs.join(" ")) return `${where}: its refs are not the records its words name`;
      }
      const cited = Array.isArray(node.passages) ? node.passages : [];
      for (const id of cited) if (!isRec(passages[String(id)])) return `${where}: names a passage that is not in the reply`;
      const blocked = refs.some((id) => !shownRecord(id))
        || cited.some((id) => (passages[String(id)] as Record<string, unknown>).state !== "available");
      if (node.state === "available" && blocked) return `${where}: shown though it names something withheld`;
      if (node.state !== "available" && !blocked) return `${where}: withheld with nothing withheld`;
    }
    for (const key of ["record", "value", "compare"]) {
      if (key in node && node[key] !== null && !known(node[key]) && !("segments" in node)) {
        return `${where}.${key}: names a record that is not in the reply`;
      }
    }
    if (Array.isArray(node.ids)) {
      const present = node.ids.filter((id) => id !== null);
      if (!present.every(known)) return `${where}.ids: names a record that is not in the reply`;
      const bases = new Set(present.map((id) => String((records[String(id)] as Record<string, unknown>).basis)));
      if (bases.size > 1) return `${where}: a row mixes bases`;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === "segments") continue;
      const problem = walk(value, `${where}.${key}`);
      if (problem) return problem;
    }
    return null;
  };
  return walk(page, "page");
}

export async function fetchCompany(signal: AbortSignal): Promise<Loaded<CompanyView>> {
  let response: Response;
  try {
    response = await fetch("/api/companies/fcx", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRec(body) && typeof body.detail === "string" ? body.detail : `Unexpected response (${response.status}).`;
    return { state: response.status === 503 ? "not-prepared" : "error", message };
  }
  const refusal = companyRefusal(body);
  if (refusal) return { state: "error", message: `The reply was refused: ${refusal}.` };
  return { state: "ready", data: body as CompanyView };
}

// ---------------------------------------------------------------- how figures read

const MINUS = "−";
const grouped = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** The figure's magnitude as shown and its sign: a published figure as printed, a computed one at its own digits. */
export function magnitude(record: FigureRecord): { text: string; negative: boolean } {
  if (record.kind === "published") {
    const display = record.display ?? "";
    const negative = display.startsWith("(") && display.endsWith(")");  // the records print a negative in parentheses
    return { text: (negative ? display.slice(1, -1) : display).replace(/%$/, ""), negative };
  }
  const value = record.value ?? "";
  const negative = value.startsWith("-");
  const [whole, fraction] = value.replace(/^-/, "").split(".");
  return { text: grouped(whole) + (fraction ? `.${fraction}` : ""), negative };
}

const DOLLAR_UNITS: Record<string, string> = {
  "USD millions": " million", "USD billions": " billion", "USD per pound": "", "USD per pound of copper": "",
  "USD per pound of molybdenum": "", "USD per ounce": "", "USD per share": "",
};
const WORD_UNITS: Record<string, string> = {
  "million recoverable pounds": "million pounds", "million pounds": "million pounds",
  "million pounds per year": "million pounds a year", "billion pounds": "billion pounds",
  "billion recoverable pounds": "billion pounds", "thousand recoverable ounces": "thousand ounces",
  "thousand ounces": "thousand ounces", "years": "years",
};

/** A figure in a sentence: "$7,546 million", "749 million pounds", "69.5%", "+$1,395 million". */
export function figureText(record: FigureRecord, mode: "signed" | "size" | null = null): string {
  const { text, negative } = magnitude(record);
  const sign = mode === "size" ? "" : negative ? MINUS : mode === "signed" && text !== "0" ? "+" : "";
  if (record.unit in DOLLAR_UNITS) return `${sign}$${text}${DOLLAR_UNITS[record.unit]}`;
  if (record.unit.startsWith("percent")) return `${sign}${text}%`;
  return `${sign}${text} ${WORD_UNITS[record.unit] ?? record.unit}`;
}

/** A figure in a table cell, without its unit words (the row names the unit): "7,546", "(1,061)", "+8.2%". */
const dollar = (record: FigureRecord) => (record.unit.startsWith("USD per") ? "$" : "");
export function cellText(record: FigureRecord, signed = false): string {
  const { text, negative } = magnitude(record);
  if (record.kind === "published" && !signed) return `${negative ? "" : dollar(record)}${record.display ?? ""}`;
  const sign = negative ? MINUS : signed && text !== "0" ? "+" : "";
  const percent = record.unit.startsWith("percent") ? "%" : "";
  return `${sign}${dollar(record)}${text}${percent}`;
}

/** Short unit words for a tile or a table's unit column. */
export function unitWords(unit: string): string {
  if (unit === "USD millions") return "US$ million";
  if (unit === "USD billions") return "US$ billion";
  if (unit.startsWith("USD per pound")) return "US$ per pound";
  if (unit === "USD per ounce") return "US$ per ounce";
  if (unit.startsWith("percent")) return unit === "percent" ? "percent" : unit;
  return WORD_UNITS[unit] ?? unit;
}

/** What kind of number a record is, for its badge: a reported figure, a company estimate (an outlook), a computation. */
export function figureKind(record: AnyRecord): "published" | "estimate" | "computed" | "assumption" {
  if (record.kind === "assumption") return "assumption";
  if (record.kind === "computed") return "computed";
  return record.period.kind === "outlook" ? "estimate" : "published";
}

export const BASIS_WORDS: Record<string, string> = {
  consolidated: "consolidated", attributable_to_common_stock: "attributable to common stock",
  noncontrolling_interests: "noncontrolling interests", net_of_noncontrolling_interests: "net of noncontrolling interests",
  company_definition: "company definition",
};
export const basisWords = (basis: string) => BASIS_WORDS[basis] ?? basis.replace(":", ": ");

export const isFigure = (record: AnyRecord | undefined): record is FigureRecord =>
  record !== undefined && record.kind !== "assumption";

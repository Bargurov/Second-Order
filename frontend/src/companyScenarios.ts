// The FCX Scenarios tab's reader (POST /api/companies/fcx/scenario, second_order/company_scenarios.py). Fail-closed: a
// reply is shown only after it names exactly the records its calculation uses, with the values the page already shows
// as verified, answers exactly the inputs that were sent, and every result recomputes exactly here as a BigInt
// fraction (price × volume and its split, or the sensitivity applied linearly), with the split adding up to the change.
// The input rules are the server's, so a bad input is named before anything is sent. Nothing is rounded: under these
// rules every result is exact. A refusal names its place, never a value.
import type { CompanyView } from "./companyResearch.ts";
import { add, div, equal, halfEven, int, lessThan, mul, ofPlain, sub, type Rat } from "./copperNumbers.ts";

export const SCENARIO_VERSION = "company-scenario-0.1";
export const SCENARIO_HEADER = "X-Second-Order-Scenario";
export const PRICE = "r3-out-cu-price-q4-2026";
export const VOLUME = "r3-out-cu-sales-q4-2026";
export const SENSITIVITY = "r3-sens-ocf-copper";
export const STEP = "r3-sens-ocf-copper-step";
export const BASE_VALUE = "c-q4-cu-sales-value-base";
export type Mode = "price_volume" | "cash_flow";
export const MODES: readonly Mode[] = ["price_volume", "cash_flow"];
/** The records each calculation uses, by role (company_scenarios.USES). */
export const USES: Record<Mode, Record<string, string>> = {
  price_volume: { price: PRICE, volume: VOLUME },
  cash_flow: { price: PRICE, sensitivity: SENSITIVITY, step: STEP },
};
const RESULTS: Record<Mode, string[]> = {
  price_volume: ["value", "base", "change", "price_effect", "volume_effect"],
  cash_flow: ["price_change", "steps", "change"],
};
const UNIT = "USD millions";

export interface Inputs { price: string; volume?: string }
export interface Use { record: string; value: string }
export interface ScenarioReply {
  view_version: string; mode: Mode; inputs: Inputs; uses: Record<string, Use>; result: Record<string, string>;
  unit: string; rests_on: string[]; stored: false; provider_called: false;
}
export type ScenarioAction = { state: "ready"; data: ScenarioReply }
  | { state: "blocked" | "failed"; message: string };

// ---------------------------------------------------------------- the input rules (company_scenarios)

const NUMBER = /^\d+(?:\.\d+)?$/;
const PRICE_TEXT = /^\d{1,3}(?:\.\d{1,2})?$/;
const VOLUME_TEXT = /^\d{1,4}(?:\.\d)?$/;
export const PRICE_RULE = "A copper price is US dollars per pound, written like 6.50: above zero and at most 100, to the cent";
export const PRICE_UNIT = "A copper price above 100 is not US dollars per pound: enter the price per pound, not per tonne or in "
  + "cents";
export const VOLUME_RULE = "Copper sold is million pounds in the quarter, written like 875: above zero and at most 5,000, with "
  + "at most one decimal";

function entered(text: string, strict: RegExp, limit: Rat, rule: string, tooLarge: string): string | null {
  if (!NUMBER.test(text)) return rule;
  const value = ofPlain(text) as Rat;
  if (lessThan(limit, value)) return tooLarge;
  return strict.test(text) && value.n > 0n ? null : rule;
}

/** Why an entered price cannot be sent, or null. */
export const priceProblem = (text: string) => entered(text, PRICE_TEXT, int(100), PRICE_RULE, PRICE_UNIT);
/** Why an entered volume cannot be sent, or null. */
export const volumeProblem = (text: string) => entered(text, VOLUME_TEXT, int(5000), VOLUME_RULE, VOLUME_RULE);

// ---------------------------------------------------------------- what the page allows

type Loose = Record<string, unknown>;
const isRec = (value: unknown): value is Loose => typeof value === "object" && value !== null && !Array.isArray(value);
const sameKeys = (value: Loose, keys: string[]) => JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());

/** Whether a calculation can run: every record it uses is shown. Otherwise the first withheld record's reason. */
export function modeState(view: CompanyView, mode: Mode): { available: boolean; problem: string | null } {
  for (const id of Object.values(USES[mode])) {
    const record = view.records[id];
    if (!record || record.state !== "available") {
      return { available: false, problem: record?.problem ?? "Not shown: a record this calculation uses is missing." };
    }
  }
  return { available: true, problem: null };
}

/** The page's scenarios must name exactly the records each calculation uses; null when they do. */
export function scenarioPageRefusal(page: Loose): string | null {
  const scenarios = page.scenarios;
  if (!isRec(scenarios)) return "page.scenarios: missing";
  for (const mode of MODES) {
    const part = scenarios[mode];
    if (!isRec(part) || !Array.isArray(part.base)) return `page.scenarios.${mode}: not a calculation`;
    const named = part.base.map((item) => (isRec(item) ? String(item.record) : "")).sort();
    if (JSON.stringify(named) !== JSON.stringify(Object.values(USES[mode]).sort())) {
      return `page.scenarios.${mode}: names other records than the calculation uses`;
    }
  }
  const baseValue = (scenarios.price_volume as Loose).base_value;
  if (!isRec(baseValue) || baseValue.record !== BASE_VALUE) return "page.scenarios.price_volume.base_value: not the base";
  return null;
}

// ---------------------------------------------------------------- a reply, checked again

function expected(mode: Mode, entered: Record<string, Rat>, used: Record<string, Rat>): Record<string, Rat> {
  if (mode === "price_volume") {
    const { price, volume } = entered;
    const value = mul(price, volume), base = mul(used.price, used.volume);
    return { value, base, change: sub(value, base), price_effect: mul(sub(price, used.price), volume),
      volume_effect: mul(sub(volume, used.volume), used.price) };
  }
  const priceChange = sub(entered.price, used.price);
  const steps = div(priceChange, used.step);
  return { price_change: priceChange, steps, change: mul(steps, used.sensitivity) };
}

/** Why a reply cannot be shown for these inputs, naming the place; null when every check passes. */
export function scenarioRefusal(reply: unknown, view: CompanyView, mode: Mode, inputs: Inputs): string | null {
  if (!isRec(reply)) return "the reply is not an object";
  if (reply.view_version !== SCENARIO_VERSION) return "view_version is not the version this page reads";
  if (reply.provider_called !== false) return "provider_called is not false";
  if (reply.stored !== false) return "stored is not false: a scenario is never stored";
  if (reply.mode !== mode) return "it answers another calculation";
  const sent: Record<string, string> = mode === "price_volume" ? { price: inputs.price, volume: inputs.volume ?? "" }
    : { price: inputs.price };
  if (priceProblem(sent.price) || (mode === "price_volume" && volumeProblem(sent.volume))) return "the inputs break the rules";
  const echoed = reply.inputs;
  if (!isRec(echoed) || !sameKeys(echoed, Object.keys(sent)) || Object.keys(sent).some((key) => echoed[key] !== sent[key])) {
    return "it answers other inputs";
  }
  if (reply.unit !== UNIT) return "unit is not US$ million";
  const roles = USES[mode];
  if (!isRec(reply.uses) || !sameKeys(reply.uses, Object.keys(roles))) return "uses: not the records this calculation uses";
  const used: Record<string, Rat> = {};
  const rests = new Set<string>();
  for (const [role, id] of Object.entries(roles)) {
    const use = reply.uses[role];
    if (!isRec(use) || use.record !== id || !sameKeys(use, ["record", "value"])) {
      return `uses.${role}: not the record this calculation uses`;
    }
    const record = view.records[id];
    if (!record || record.kind === "assumption" || record.state !== "available" || record.value === null) {
      return `uses.${role}: it rests on a record that is not shown on the page`;
    }
    if (use.value !== record.value) return `uses.${role}: its value is not the page's`;
    used[role] = ofPlain(record.value) as Rat;
    for (const sid of (record as unknown as { rests_on?: string[] }).rests_on ?? []) rests.add(sid);
  }
  if (JSON.stringify(reply.rests_on) !== JSON.stringify([...rests].sort())) return "rests_on: not the documents of its records";
  const result = reply.result;
  if (!isRec(result) || !sameKeys(result, RESULTS[mode])) return "result: not this calculation's results";
  const entered: Record<string, Rat> = Object.fromEntries(Object.entries(sent).map(([key, text]) => [key, ofPlain(text) as Rat]));
  const want = expected(mode, entered, used);
  for (const key of RESULTS[mode]) {
    const shown = ofPlain(result[key]);
    if (shown === null) return `result.${key}: not an exact number`;
    if (!equal(shown, want[key])) return `result.${key}: does not follow from the inputs and the records`;
  }
  if (mode === "price_volume") {
    const parts = add(ofPlain(result.price_effect) as Rat, ofPlain(result.volume_effect) as Rat);
    if (!equal(parts, ofPlain(result.change) as Rat)) return "result.change: the price and volume effects do not add up to it";
    const base = view.records[BASE_VALUE];
    if (base?.kind === "computed" && base.state === "available" && base.value !== null
      && !equal(ofPlain(base.value) as Rat, ofPlain(result.base) as Rat)) return "result.base: not the page's base";
  }
  return null;
}

/** One calculation for these inputs, read fail-closed. A 409 is a calculation blocked by an unverified document. */
export async function computeScenario(view: CompanyView, mode: Mode, inputs: Inputs): Promise<ScenarioAction> {
  const body = mode === "price_volume" ? { mode, price: inputs.price, volume: inputs.volume } : { mode, price: inputs.price };
  let response: Response;
  try {
    response = await fetch("/api/companies/fcx/scenario", { method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", Accept: "application/json", [SCENARIO_HEADER]: "1" } });
  } catch {
    return { state: "failed", message: "No reply arrived from the local server. Nothing was computed or stored." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRec(payload) && typeof payload.detail === "string" ? payload.detail
      : `Unexpected response (${response.status}).`;
    return { state: response.status === 409 ? "blocked" : "failed", message };
  }
  const refusal = scenarioRefusal(payload, view, mode, inputs);
  if (refusal) return { state: "failed", message: `The reply was refused: ${refusal}.` };
  return { state: "ready", data: payload as unknown as ScenarioReply };
}

// ---------------------------------------------------------------- how amounts read

const MINUS = "−";
const grouped = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** An exact amount in US$ million as the server writes it: "$5,775 million", "+$87.5 million", "−$97.5 million". */
export function money(value: string, signed = false): string {
  const negative = value.startsWith("-");
  const [whole, fraction] = value.replace(/^-/, "").split(".");
  const zero = /^0*$/.test(whole) && (!fraction || /^0*$/.test(fraction));
  const sign = zero ? "" : negative ? MINUS : signed ? "+" : "";
  return `${sign}$${grouped(whole)}${fraction ? `.${fraction}` : ""} million`;
}

/** An entered price to the cent: "$6.60". */
export const priceText = (value: string) => `$${halfEven(ofPlain(value) as Rat, 2)}`;
/** An entered volume as written, grouped: "1,234.5 million pounds". */
export function volumeText(value: string): string {
  const [whole, fraction] = value.split(".");
  return `${grouped(whole.replace(/^0+(?=\d)/, ""))}${fraction ? `.${fraction}` : ""} million pounds`;
}
/** Whether a number of the company's steps is more than one, either way: the company states its figure for one. */
export function beyondOneStep(steps: string): boolean {
  const value = ofPlain(steps);
  return value !== null && lessThan(int(1), value.n < 0n ? { n: -value.n, d: value.d } : value);
}

/** A signed exact number with no unit, as the formula lines show it: "+1", "−1.3". */
export function signedNumber(value: string): string {
  const negative = value.startsWith("-");
  const body = value.replace(/^-/, "");
  return `${negative ? MINUS : body === "0" ? "" : "+"}${body}`;
}

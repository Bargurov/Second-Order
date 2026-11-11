// Cross-source comparisons: reads of the stored, verified result and the one explicit local computation. The server
// computes and words everything; this module refuses replies whose numbers or labels do not follow from their own
// values, and never repeats the computation.
import type { Loaded } from "./api";

export const CROSS_SOURCE_VIEW_VERSION = "cross-source-view-0.1";
/** The same request header as the other findings checks (insights.ts INSIGHTS_HEADER); a test keeps them equal. */
export const CROSS_SOURCE_INSIGHTS_HEADER = "X-Second-Order-Insights";
export const CLASSES = ["ESRCPUS", "ESCCPUS", "ESICPUS", "ESACPUS"] as const;
export const CLASS_LABEL: Record<string, string> = {
  ESRCPUS: "Residential", ESCCPUS: "Commercial", ESICPUS: "Industrial", ESACPUS: "Transportation (railways only)",
};
export type Signs = "same_sign" | "opposite_signs" | "no_direction" | "not_covered" | "unavailable" | "not_printed";

export interface EiaChange {
  code: string; months: string[]; prior_months: string[]; current: string | null; prior: string | null;
  change: string | null; percent: string | null; sign: -1 | 0 | 1 | null;
  state: "computed" | "not_covered" | "unavailable"; reason: string | null;
}
export interface G17Cell {
  state: "printed" | "blank" | "not_printed"; value: string | null; sign: -1 | 0 | 1 | null; release: string | null;
  release_date_as_stated?: string; marker?: string | null; column?: string; path?: string; naics?: string;
  sha256?: string; url?: string; extract_id?: string; vintages: { release: string; release_date_as_stated: string;
    value: string | null }[]; vintages_differ?: boolean;
}
export interface Breakdown {
  state: "computed" | "unavailable"; detail: string | null; sectors: Record<string, string> | null;
  total_change: string | null; residual_change: string | null; analyzed_change: string | null;
}
export interface IndustrialRow { period: string; kind: string; label: string; eia: EiaChange; g17: G17Cell; signs: Signs }
export interface UtilityRow {
  period: string; kind: string; label: string; g17: G17Cell; eia_total: EiaChange;
  eia_classes: Record<string, EiaChange>; breakdown: Breakdown;
}
export interface ComparisonText {
  title: string; question: string; eia_measure: string; g17_measure: string; differences: string[];
  possibilities: string[]; possibilities_note: string | null; link: { section: string; label: string };
  link_g17: { section: string; label: string };
}
export interface CrossSourceView {
  view_version: string; state: "not_checked" | "checked" | "problem"; detail: string | null; scope: string;
  available: boolean; sources_detail: string | null; kept_results: number; written: false; provider_called: false;
  definitions: Record<string, unknown>; sign_labels: Record<Signs, string>; sign_note: string;
  common_limitations: string[];
  comparisons_text: { industrial_vs_manufacturing: ComparisonText; utility_output_and_customers: ComparisonText };
  result: { result_id: string; computed_at: string; rules_version: string; definitions_sha256: string } | null;
  sources: {
    g17: { release: string; release_date_as_stated: string; file: string; url: string; sha256: string;
      approval_id: string; retrieved_at: string | null; extract_id: string }[];
    eia: { file: string; url: string; sha256: string; retrieved_at: string | null; edition: null; edition_note: string;
      monthly_first: string; monthly_last: string; approval_id: string };
  } | null;
  periods: { key: string; kind: "fourth_quarter" | "twelve_month"; label: string; months: string[];
    prior_months: string[]; year?: number }[];
  comparisons: { industrial_vs_manufacturing: IndustrialRow[]; utility_output_and_customers: UtilityRow[] } | null;
}
export interface CheckOutcome {
  view_version: string; result_id: string; created: boolean; periods: number; provider_called: false;
}

const SHA = /^[0-9a-f]{64}$/;
const RATE = /^-?\d*\.\d$/;
const PERCENT = /^-?\d+\.\d\d$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";
const FOURTH_QUARTERS = ["2023-Q4", "2024-Q4", "2025-Q4"];

const DECIMAL = /^-?\d+(\.\d{1,4})?$/;

/** An exact decimal (up to four places) as ten-thousandths; the same as electricity.ts units, kept local so this module
 * has no runtime import (a test checks they agree). */
export function units(text: string): bigint {
  if (!DECIMAL.test(text)) throw new Error(`not a decimal: ${text}`);
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const value = BigInt(whole) * 10_000n + BigInt(fraction.padEnd(4, "0"));
  return negative ? -value : value;
}

function sign(value: bigint): -1 | 0 | 1 {
  return value === 0n ? 0 : value > 0n ? 1 : -1;
}

/** A G.17 printed rate's sign: a printed 0.0 or -0.0 has no direction (0). */
export function rateSign(text: string): -1 | 0 | 1 {
  return sign(units(text.startsWith(".") || text.startsWith("-.") ? text.replace(".", "0.") : text));
}

/** An EIA change is read only when it follows exactly from its two totals, with the percentage truncated. */
export function eiaOk(item: EiaChange, code: string): boolean {
  if (item.code !== code) return false;
  if (item.state !== "computed") return item.change === null && item.sign === null && !!item.reason;
  if (item.current === null || item.prior === null || item.change === null || item.percent === null) return false;
  try {
    const current = units(item.current), prior = units(item.prior), change = units(item.change);
    if (prior <= 0n || current - prior !== change || !PERCENT.test(item.percent)) return false;
    return units(item.percent) / 100n === (change * 10_000n) / prior && item.sign === sign(change);
  } catch {
    return false;
  }
}

function g17Ok(cell: G17Cell, releases: Map<string, string>): boolean {
  if (cell.state === "not_printed") return cell.value === null && cell.release === null;
  if (!cell.release || releases.get(cell.release) !== cell.sha256 || !cell.column) return false;
  if (cell.state === "blank") return cell.value === null && cell.sign === null;
  return cell.value !== null && RATE.test(cell.value) && cell.sign === rateSign(cell.value);
}

/** The sign-only description, recomputed from the two sides. */
export function expectedSigns(eia: EiaChange, g17: G17Cell): Signs {
  if (eia.state !== "computed") return eia.state;
  if (g17.state !== "printed") return g17.state === "not_printed" ? "not_printed" : "unavailable";
  if (eia.sign === 0 || g17.sign === 0) return "no_direction";
  return eia.sign === g17.sign ? "same_sign" : "opposite_signs";
}

function breakdownOk(found: Breakdown, total: EiaChange, classes: Record<string, EiaChange>): boolean {
  if (found.state !== "computed") return found.state === "unavailable" && found.sectors === null;
  if (total.state !== "computed" || !found.sectors || found.total_change === null || found.residual_change === null)
    return false;
  try {
    const parts = CLASSES.map((code) => units(found.sectors![code]));
    if (parts.reduce((a, b) => a + b, 0n) + units(found.residual_change) !== units(found.total_change)) return false;
    if (found.total_change !== total.change) return false;
    return CLASSES.every((code) => classes[code]?.state !== "computed" || classes[code].change === found.sectors![code]);
  } catch {
    return false;
  }
}

/** A view is read only at this version, writing nothing, with every row following from its own values. */
export function isCrossSourceView(body: unknown): boolean {
  if (typeof body !== "object" || body === null) return false;
  const view = body as CrossSourceView;
  if (view.view_version !== CROSS_SOURCE_VIEW_VERSION || view.written !== false || view.provider_called !== false)
    return false;
  if (!["not_checked", "checked", "problem"].includes(view.state)) return false;
  if (view.state !== "checked") return view.comparisons === null && view.result === null && view.periods.length === 0;
  const comparisons = view.comparisons, sources = view.sources;
  if (!comparisons || !sources || !view.result || !SHA.test(view.result.result_id) || !SHA.test(sources.eia.sha256) ||
      sources.eia.edition !== null) return false;
  const releases = new Map(sources.g17.map((item) => [item.release, item.sha256]));
  const keys = view.periods.map((period) => period.key);
  if (keys.slice(0, 3).join() !== FOURTH_QUARTERS.join() ||
      !keys.slice(3).every((key, i, rest) => /^\d{4}-\d{2}$/.test(key) && (i === 0 || key > rest[i - 1]))) return false;
  const industrial = comparisons.industrial_vs_manufacturing, utility = comparisons.utility_output_and_customers;
  if (industrial.map((row) => row.period).join() !== keys.join() || utility.map((row) => row.period).join() !==
      keys.join()) return false;
  return industrial.every((row) => eiaOk(row.eia, "ESICPUS") && g17Ok(row.g17, releases) &&
      (row.g17.state === "not_printed" || row.g17.path?.endsWith("Manufacturing (NAICS)")) &&
      row.signs === expectedSigns(row.eia, row.g17)) &&
    utility.every((row) => eiaOk(row.eia_total, "ESTCPUS") && g17Ok(row.g17, releases) &&
      (row.g17.state === "not_printed" || row.g17.path?.endsWith("Utilities / Electric")) &&
      CLASSES.every((code) => eiaOk(row.eia_classes[code], code)) &&
      breakdownOk(row.breakdown, row.eia_total, row.eia_classes));
}

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail : null;
}

export async function fetchCrossSource(signal: AbortSignal): Promise<Loaded<CrossSourceView>> {
  let response: Response;
  try {
    response = await fetch("/api/insights/cross-source", { signal, headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 404) return { state: "missing", message: detail(body) ?? "Not found." };
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if (!isCrossSourceView(body)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body as CrossSourceView };
}

export type CheckResult =
  | { state: "done"; data: CheckOutcome }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string };

/** The explicit local computation. A missing reply is "unconfirmed"; nothing is sent again. */
export async function runCrossSourceCheck(): Promise<CheckResult> {
  let response: Response;
  try {
    response = await fetch("/api/insights/cross-source/checks", {
      method: "POST", body: JSON.stringify({ check_cross_source: true }),
      headers: { "Content-Type": "application/json", Accept: "application/json", [CROSS_SOURCE_INSIGHTS_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Reload the page to see whether "
      + "the result was stored; nothing was sent again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.status >= 500) return { state: "unconfirmed", message: detail(payload) ?? "The server failed." };
  if (!response.ok) return { state: "refused", message: detail(payload) ?? `Refused (${response.status}).` };
  const value = payload as CheckOutcome | null;
  if (!value || value.view_version !== CROSS_SOURCE_VIEW_VERSION || !SHA.test(value.result_id)) {
    return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  }
  return { state: "done", data: value };
}

/** A G.17 printed rate as published: "+1.4%", "−0.5%", "0.0%" (a printed 0.0 keeps its decimal). */
export function printed(text: string | null): string {
  if (text === null) return "blank";
  const negative = text.startsWith("-");
  const digits = text.replace("-", "").replace(/^\./, "0.");
  return /^0\.0$/.test(digits) ? `${negative ? "−" : ""}0.0%` : `${negative ? "−" : "+"}${digits}%`;
}

export const KIND_NOTE: Record<string, string> = {
  fourth_quarter: "EIA: October–December total against the same months a year earlier. G.17: fourth quarter to "
    + "fourth quarter, as printed.",
  twelve_month: "EIA: the month against the same month a year earlier. G.17: the 12-month change, as printed.",
};

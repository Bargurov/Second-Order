// Electricity by sector from retained EIA Table 7.6: reads of the stored, verified result and the one explicit local
// check. The server compares and words everything; this module refuses replies whose numbers do not hold together and
// never repeats the check.
import type { Loaded } from "./api";

export const ELECTRICITY_VIEW_VERSION = "electricity-view-0.1";
/** The same request header as the other findings checks (insights.ts INSIGHTS_HEADER); a test keeps them equal. */
export const ELECTRICITY_INSIGHTS_HEADER = "X-Second-Order-Insights";
export const ANALYZED = ["ESRCPUS", "ESCCPUS", "ESICPUS"] as const;
export const CONTEXT = ["ESACPUS", "ESTCPUS"] as const;
export const SECTORS = ["ESRCPUS", "ESCCPUS", "ESICPUS", "ESACPUS"] as const;

export type Class = "up" | "down" | "little_changed" | "unavailable";
export interface Comparison {
  code: string; key: string; label: string; role: "analyzed" | "context"; current: string | null;
  prior: string | null; change: string | null; percent: string | null; class: Class; reason: string | null;
}
export interface Groups {
  up: string[]; down: string[]; little_changed: string[]; unavailable: string[]; finding: boolean;
}
export interface Contributions {
  state: "computed" | "unavailable"; detail: string | null; sectors: Record<string, string> | null;
  total_change: string | null; residual_change: string | null; analyzed_change: string | null;
  rows?: { code: string; label: string; change: string; role: "analyzed" | "context" }[];
}
export interface Reconciled {
  month: string; state: "within_rounding" | "beyond_rounding" | "unavailable"; sum: string | null;
  total: string | null; residual: string | null;
}
export interface MonthRow {
  month: string; label: string; prior: string; prior_label: string; days: number; prior_days: number;
  sectors: Comparison[]; context: Comparison[]; divergence: Groups; reconciliation: Reconciled[];
  contributions: Contributions; days_note: string;
}
export interface Period {
  label: string; prior_label: string; months: string[]; prior_months: string[]; days: number; prior_days: number;
  sectors: Comparison[]; context: Comparison[]; divergence: Groups; contributions: Contributions; days_note: string;
}
export interface Card {
  type: "month" | "period"; id: string; key: string; label: string; prior_label: string; title: string;
  observed: Comparison[]; adds: string; interpretation: string;
  others: { little_changed: string[]; unavailable: string[] }; contributions: Contributions; notes: string[];
  disclosures: string[]; source: { file: string; url: string; sha256: string; retrieved_at: string | null };
}
export interface Source {
  kind: "csv" | "pdf" | "landing"; role: string; file?: string; url?: string; sha256?: string; bytes?: number;
  approval_id?: string; retrieved_at?: string | null; completed_at?: string | null; content_type?: string | null;
  last_modified_header?: string | null; content_disposition?: string | null; edition?: string | null;
  edition_note?: string; edition_printed?: string; unavailable?: string;
  statements?: { release_date_as_stated: string | null; next_release_as_stated: string | null; readable: boolean };
}
export interface Coverage {
  compared: { first: string; last: string; first_label: string; last_label: string };
  against: { first: string; last: string; first_label: string; last_label: string };
  period: { label: string; prior_label: string }; geography: string;
  file: { monthly_first: string; monthly_last: string; monthly_last_label: string; annual_first: string | null;
    annual_last: string | null; retrieved_at: string | null };
}
export interface ElectricityView {
  view_version: string; state: "not_checked" | "checked" | "problem"; detail: string | null; scope: string;
  available: boolean; sources_detail: string | null; kept_results: number; written: false; provider_called: false;
  definitions: Record<string, unknown>; table_definitions: {
    title: string; unit: string; edition_printed: string; footnotes: Record<string, string>; notes: string[];
    markers: string; web_page: string; not_retained: string; columns: Record<string, string>;
    transcribed_from: { url: string; sha256: string; how: string };
  };
  disclosures: string[]; limitations: string[];
  result: { result_id: string; computed_at: string; rules_version: string; definitions_sha256: string;
    extract_id: string } | null;
  coverage: Coverage | null; sources: Source[];
  series: { code: string; column_order: string; description: string; unit: string; label: string;
    role: "analyzed" | "context" | "excluded" }[];
  months: MonthRow[]; period: Period | null;
  findings: { order: string; monthly: Card[]; period: Card | null; total: number } | null;
  reconciliation: { months: Reconciled[]; tolerance: string; max_abs_residual: string | null;
    counts: Record<"within_rounding" | "beyond_rounding" | "unavailable", number> } | null;
}
export interface CheckOutcome {
  view_version: string; result_id: string; created: boolean; months: number; monthly_findings: number;
  period_finding: boolean; provider_called: false;
}

const SHA = /^[0-9a-f]{64}$/;
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const DECIMAL = /^-?\d+(\.\d{1,4})?$/;
const PERCENT = /^-?\d+\.\d\d$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";
const SCALE = 10_000n;

/** An exact decimal (up to four places) as an integer number of ten-thousandths. */
export function units(text: string): bigint {
  if (!DECIMAL.test(text)) throw new Error(`not a decimal: ${text}`);
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const value = BigInt(whole) * SCALE + BigInt(fraction.padEnd(4, "0"));
  return negative ? -value : value;
}

function shift(month: string, by: number): string {
  const index = Number(month.slice(0, 4)) * 12 + Number(month.slice(5)) - 1 + by;
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String(index % 12 + 1).padStart(2, "0")}`;
}

/** Percentage of change on prior, two decimals truncated toward zero, as hundredths (exact). */
function hundredths(change: bigint, prior: bigint): bigint {
  return (change * 10_000n) / prior; // BigInt division truncates toward zero.
}

/** A comparison is read only when its class, change and percentage follow exactly from its two values. */
export function comparisonOk(item: Comparison): boolean {
  if (item.class === "unavailable") return item.change === null && item.percent === null && !!item.reason;
  if (item.current === null || item.prior === null || item.change === null || item.percent === null) return false;
  if (!PERCENT.test(item.percent) || item.reason !== null) return false;
  try {
    const current = units(item.current), prior = units(item.prior), change = units(item.change);
    if (prior <= 0n || current - prior !== change) return false;
    const shown = units(item.percent) / 100n; // percent in hundredths
    if (shown !== hundredths(change, prior)) return false;
    const exact = change * 100n; // compared with the prior, as the rule does
    const expected: Class = exact >= prior ? "up" : exact <= -prior ? "down" : "little_changed";
    return item.class === expected;
  } catch {
    return false;
  }
}

function sameList(a: unknown[], b: unknown[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

function groupsOk(groups: Groups, sectors: Comparison[]): boolean {
  const named = (cls: Class) => sectors.filter((item) => item.class === cls).map((item) => item.label);
  return sameList(groups.up, named("up")) && sameList(groups.down, named("down")) &&
    sameList(groups.little_changed, named("little_changed")) && sameList(groups.unavailable, named("unavailable")) &&
    groups.finding === (groups.up.length > 0 && groups.down.length > 0);
}

function rowsOk(sectors: Comparison[], context: Comparison[]): boolean {
  return sameList(sectors.map((item) => item.code), [...ANALYZED]) &&
    sectors.every((item) => item.role === "analyzed") &&
    sameList(context.map((item) => item.code), [...CONTEXT]) && context.every((item) => item.role === "context") &&
    [...sectors, ...context].every(comparisonOk);
}

/** Contributions are read only when the sectors' changes and the residual make up the total change exactly, and the
 * total change is the one the total's own comparison shows. */
export function contributionsOk(found: Contributions, sectors: Comparison[], context: Comparison[]): boolean {
  if (found.state !== "computed") return found.state === "unavailable" && !!found.detail && found.sectors === null;
  if (!found.sectors || !found.rows || found.total_change === null || found.residual_change === null ||
      found.analyzed_change === null) return false;
  try {
    if (!sameList(found.rows.map((row) => row.code), [...SECTORS])) return false;
    const changes = found.rows.map((row) => units(row.change));
    if (found.rows.some((row) => row.change !== found.sectors![row.code])) return false;
    const total = units(found.total_change), residual = units(found.residual_change);
    if (changes.reduce((a, b) => a + b, 0n) + residual !== total) return false;
    if (units(found.analyzed_change) !== changes.slice(0, 3).reduce((a, b) => a + b, 0n)) return false;
    const totalRow = context.find((item) => item.code === "ESTCPUS");
    const byCode = new Map([...sectors, ...context].map((item) => [item.code, item]));
    if (found.rows.some((row) => byCode.get(row.code)?.change !== null && byCode.get(row.code)?.change !== row.change))
      return false;
    return totalRow?.change === null || totalRow?.change === found.total_change;
  } catch {
    return false;
  }
}

function cardOk(card: Card, rows: Comparison[], groups: Groups, view: ElectricityView, csvSha: string): boolean {
  return JSON.stringify(card.observed) === JSON.stringify(rows) && sameList(card.disclosures, view.disclosures) &&
    card.disclosures.length === 6 && card.source.sha256 === csvSha && groups.finding &&
    card.title.includes(" up, ") && card.title.includes(" down from ");
}

/** A view is read only at this version, writing nothing, with every cross-section identity holding. */
export function isElectricityView(body: unknown): boolean {
  if (typeof body !== "object" || body === null) return false;
  const view = body as ElectricityView;
  if (view.view_version !== ELECTRICITY_VIEW_VERSION || view.written !== false || view.provider_called !== false)
    return false;
  if (!["not_checked", "checked", "problem"].includes(view.state) || !Array.isArray(view.disclosures) ||
      view.disclosures.length !== 6) return false;
  if (view.state !== "checked") return view.findings === null && view.result === null && view.months.length === 0;
  const result = view.result, coverage = view.coverage, findings = view.findings, period = view.period;
  if (!result || !coverage || !findings || !period || !view.reconciliation || !SHA.test(result.result_id))
    return false;
  const csv = view.sources.find((source) => source.kind === "csv");
  const pdf = view.sources.find((source) => source.kind === "pdf");
  if (!csv || !pdf || !SHA.test(csv.sha256 ?? "") || !SHA.test(pdf.sha256 ?? "") || csv.edition !== null) return false;
  const months = view.months;
  if (months.length !== 12 || months[0].month !== coverage.compared.first || months.at(-1)!.month !==
      coverage.compared.last) return false;
  const monthsOk = months.every((row, i) => MONTH.test(row.month) && (i === 0 || row.month === shift(months[i - 1].month,
    1)) && row.prior === shift(row.month, -12) && rowsOk(row.sectors, row.context) &&
    groupsOk(row.divergence, row.sectors) && contributionsOk(row.contributions, row.sectors, row.context));
  if (!monthsOk || !rowsOk(period.sectors, period.context) || !groupsOk(period.divergence, period.sectors) ||
      !contributionsOk(period.contributions, period.sectors, period.context)) return false;
  const expected = months.filter((row) => row.divergence.finding).map((row) => row.month).reverse();
  if (!sameList(findings.monthly.map((card) => card.key), expected)) return false;
  const byMonth = new Map(months.map((row) => [row.month, row]));
  if (!findings.monthly.every((card) => {
    const row = byMonth.get(card.key)!;
    return card.type === "month" && cardOk(card, [...row.sectors, ...row.context], row.divergence, view, csv.sha256!);
  })) return false;
  if ((findings.period !== null) !== period.divergence.finding) return false;
  if (findings.period && !cardOk(findings.period, [...period.sectors, ...period.context], period.divergence, view,
    csv.sha256!)) return false;
  if (findings.total !== findings.monthly.length + (findings.period ? 1 : 0)) return false;
  const counts = view.reconciliation.counts;
  return counts.within_rounding + counts.beyond_rounding + counts.unavailable === view.reconciliation.months.length &&
    view.reconciliation.months.every((item) => item.state === "unavailable" ? item.residual === null
      : item.residual !== null && units(item.total!) - units(item.sum!) === units(item.residual));
}

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail : null;
}

export async function fetchElectricity(signal: AbortSignal): Promise<Loaded<ElectricityView>> {
  let response: Response;
  try {
    response = await fetch("/api/insights/electricity", { signal, headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 404) return { state: "missing", message: detail(body) ?? "Not found." };
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if (!isElectricityView(body)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body as ElectricityView };
}

export type CheckResult =
  | { state: "done"; data: CheckOutcome }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string };

/** The explicit local check. A missing reply is "unconfirmed"; nothing is sent again. */
export async function runElectricityCheck(): Promise<CheckResult> {
  let response: Response;
  try {
    response = await fetch("/api/insights/electricity/checks", {
      method: "POST", body: JSON.stringify({ check_retained_electricity: true }),
      headers: { "Content-Type": "application/json", Accept: "application/json", [ELECTRICITY_INSIGHTS_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Reload the page to see whether "
      + "the result was stored; nothing was sent again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.status >= 500) return { state: "unconfirmed", message: detail(payload) ?? "The server failed." };
  if (!response.ok) return { state: "refused", message: detail(payload) ?? `Refused (${response.status}).` };
  const value = payload as CheckOutcome | null;
  if (!value || value.view_version !== ELECTRICITY_VIEW_VERSION || !SHA.test(value.result_id)) {
    return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  }
  return { state: "done", data: value };
}

/** A level in million kWh with thousands separators, exact: "101,000.000". */
export function level(text: string | null): string {
  if (text === null) return "—";
  const negative = text.startsWith("-");
  const [whole, fraction] = text.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}${fraction !== undefined ? `.${fraction}` : ""}`;
}

/** A change in million kWh with its sign: "+1,000.000", "−800.000", "0.000". */
export function signed(text: string | null): string {
  if (text === null) return "—";
  const zero = /^-?0(\.0+)?$/.test(text);
  return zero ? level(text.replace("-", "")) : text.startsWith("-") ? level(text) : `+${level(text)}`;
}

/** A percentage as served (two decimals, truncated toward zero): "+1.00%", "−2.45%", "0.00%". */
export function percent(text: string | null): string {
  if (text === null) return "not available";
  if (text === "0.00") return "0.00%";
  return text.startsWith("-") ? `−${text.slice(1)}%` : `+${text}%`;
}

export const CLASS_LABEL: Record<Class, string> = {
  up: "Up (≥ +1%)", down: "Down (≤ −1%)", little_changed: "Little changed", unavailable: "Not available",
};

export const SHORT: Record<string, string> = { ESRCPUS: "R", ESCCPUS: "C", ESICPUS: "I" };

// The Treasury findings pilot: reads of stored findings and the one explicit local check. The server measures and
// words everything; this module shapes the request, refuses replies it cannot read, and never repeats the check.
import type { Loaded } from "./api";

export const INSIGHT_VIEW_VERSION = "insight-view-0.1";
export const INSIGHTS_HEADER = "X-Second-Order-Insights";

export interface PackageInfo {
  package_id: string; sha256: string; received_at: string; requested_at?: string; release_prepared?: string | null;
  extract_version?: string; cutoff: string | null; last_date: string | null;
}
export interface RecordRow {
  origin: "capture" | "inbox" | "library"; origin_id: string; title: string; basis: string | null;
  as_stated: string | null; problem: string | null; href: string; note?: string | null;
}
export interface EventRow {
  key: string; title: string; link: string; publisher: string | null; family_label: string | null; date: string | null;
  state: "dated" | "unsupported" | "no_date" | "date_conflict"; detail: string | null; records: RecordRow[];
  checked: boolean;
}
export interface OccasionRow {
  date: string; state: "checked" | "unavailable" | "problem"; result_id: string | null; detail: string | null;
  events: string[]; findings?: number; evaluable?: number; checks?: number; problem?: string | null;
}
export interface Comparison {
  comparison_id: string; seed: string; size: number; range: [string, string]; candidates: number;
  any?: { met: number; evaluable: number }; note?: string;
}
export interface Listing {
  view_version: string; scope: string; limitations: string[]; definitions: { rules: Record<string, string> } &
    Record<string, unknown>;
  bases: Record<string, string>; origins: Record<string, string>;
  check: { check_id: string; checked_at: string; package: PackageInfo } | null; occasions: OccasionRow[];
  events: EventRow[]; unchecked: string[]; comparison: Comparison | null; written: false; provider_called: false;
}
export interface Endpoint { date: string; values: { series_id: string; sign: number; text: string | null }[] }
export interface MeasureRow {
  key: string; measure: string; label: string; window: string; window_label: string; span: number; start: Endpoint;
  end: Endpoint; change_bp: string | null; rank: string | null; smaller: number | null; equal: number | null;
  eligible: number | null; candidates: number | null; reference_first_end: string | null;
  reference_last_end: string | null; problem: string | null;
}
export interface Frequency { met: number; evaluable: number; sessions: number }
export interface Finding {
  check: string; rule: string; rule_text: string; title: string; window: string | null; window_label: string | null;
  observations: string[]; adds: string; inference: string; alternatives: string[]; strengthen: string[];
  weaken: string[]; frequency: Frequency | null;
}
export interface OtherCheck {
  check: string; rule: string; subject: string | null; window: string | null; outcome: "not_met" | "not_evaluable";
  detail: string | null; frequency: Frequency | null;
}
export interface Rendered {
  text_version: string; date: string; summary: string; event_on_grid: boolean | null;
  windows: Record<string, { start: string; end: string; span: number; label: string }>; measures: MeasureRow[];
  findings: Finding[]; other_checks: OtherCheck[]; policy_changes: { date: string; from: string; to: string }[];
  nearby: { date: string; title: string; key: string }[];
  series: Record<string, { short: string; long: string; attributes: Record<string, string> }>;
  rules: Record<string, string>; comparison: Comparison | null;
}
export interface OccasionView {
  view_version: string; date: string; events: EventRow[]; scope: string; limitations: string[];
  bases: Record<string, string>; origins: Record<string, string>; state: string; detail: string | null;
  result: Rendered | null;
  provenance?: { computed_from: PackageInfo; attested_by: PackageInfo[]; result_id: string; inputs_sha256: string;
    definitions_sha256: string };
}
export interface Band {
  view_version: string; kind: string; id: string; scope: string; state: string; event: EventRow | null;
  occasion: (Partial<OccasionRow> & { date: string }) | null;
}
export interface CheckOutcome {
  view_version: string; check_id: string; created: boolean; results_created: number; occasions: number;
  package: PackageInfo; provider_called: false;
}

const SHA = /^[0-9a-f]{64}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail : null;
}

function versioned(body: unknown): Record<string, unknown> | null {
  if (typeof body !== "object" || body === null) return null;
  const value = body as Record<string, unknown>;
  return value.view_version === INSIGHT_VIEW_VERSION ? value : null;
}

export function isListing(body: unknown): boolean {
  const value = versioned(body);
  return !!value && Array.isArray(value.occasions) && Array.isArray(value.events) && value.written === false &&
    value.provider_called === false && (value.occasions as OccasionRow[]).every((row) => DAY.test(row.date) &&
      (row.result_id === null || SHA.test(row.result_id)));
}

/** A rendered occasion is read only when it is the date asked for and every finding cites measures it shows. */
export function isOccasion(body: unknown, day: string): boolean {
  const value = versioned(body);
  if (!value || value.date !== day || !Array.isArray(value.events)) return false;
  const result = value.result as Rendered | null;
  if (result === null) return true;
  if (result.date !== day || !Array.isArray(result.measures) || !Array.isArray(result.findings)) return false;
  const keys = new Set(result.measures.map((row) => row.key));
  return result.findings.every((finding) => finding.observations.length > 0 &&
    finding.observations.every((key) => keys.has(key)));
}

export function isBand(body: unknown): boolean {
  const value = versioned(body);
  return !!value && typeof value.state === "string";
}

async function read<T>(path: string, signal: AbortSignal, accept: (body: unknown) => boolean): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 404) return { state: "missing", message: detail(body) ?? "Not found." };
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if (!accept(body)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body as T };
}

export const fetchListing = (signal: AbortSignal) => read<Listing>("/api/insights", signal, isListing);
export const fetchOccasion = (day: string, signal: AbortSignal) =>
  read<OccasionView>(`/api/insights/occasions/${encodeURIComponent(day)}`, signal, (body) => isOccasion(body, day));
export const fetchBand = (kind: string, id: string, signal: AbortSignal) =>
  read<Band>(`/api/insights/events/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, signal, isBand);

export type CheckResult =
  | { state: "done"; data: CheckOutcome }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string };

/** The explicit local check. A missing reply is "unconfirmed"; nothing is sent again by itself. */
export async function runCheck(): Promise<CheckResult> {
  let response: Response;
  try {
    response = await fetch("/api/insights/checks", {
      method: "POST", body: JSON.stringify({ check_retained_evidence: true }),
      headers: { "Content-Type": "application/json", Accept: "application/json", [INSIGHTS_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Reload the page to see whether "
      + "the check was recorded; nothing was sent again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.status >= 500) return { state: "unconfirmed", message: detail(payload) ?? "The server failed." };
  if (!response.ok) return { state: "refused", message: detail(payload) ?? `Refused (${response.status}).` };
  const value = versioned(payload);
  if (!value || typeof value.check_id !== "string" || !SHA.test(value.check_id)) {
    return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  }
  return { state: "done", data: payload as CheckOutcome };
}

export function occasionHref(day: string): string {
  return `/findings/${encodeURIComponent(day)}`;
}

export const EVENT_STATE: Record<EventRow["state"], string> = {
  dated: "Dated", unsupported: "Outside this pilot", no_date: "No usable date", date_conflict: "Dates disagree",
};

/** How an occasion reads in a list: its findings count, or that nothing met the rules, or why it was not measured. */
export function occasionStatus(row: Pick<OccasionRow, "state" | "findings" | "detail">): string {
  if (row.state === "checked") {
    return row.findings ? `${row.findings} finding${row.findings === 1 ? "" : "s"}` : "Checked · nothing met the rules";
  }
  return row.state === "problem" ? `Not shown: ${row.detail ?? "the stored result does not verify"}`
    : `Not measured: ${row.detail ?? "unavailable"}`;
}

/** A change in bp with its sign; "unavailable" when there is none. */
export function bp(text: string | null): string {
  if (text === null) return "unavailable";
  return `${Number(text) > 0 ? "+" : ""}${text} bp`;
}

/** A rank as "0.93 (larger than 232 and equal to 1 of 250)". */
export function rankText(row: Pick<MeasureRow, "rank" | "smaller" | "equal" | "eligible">): string {
  if (row.rank === null || row.eligible === null) return "no rank";
  return `${Number(row.rank).toFixed(2)} (exceeds ${row.smaller} and equals ${row.equal} of ${row.eligible})`;
}

// Industry findings from retained G.17 releases: reads of stored, verified results and the one explicit local check.
// The server compares and words everything; this module refuses replies it cannot read and never repeats the check.
import type { Loaded } from "./api";

export const G17_VIEW_VERSION = "g17-view-0.1";
/** The same request header as the Treasury check (insights.ts INSIGHTS_HEADER); a test keeps them equal. */
export const G17_INSIGHTS_HEADER = "X-Second-Order-Insights";

export interface Source {
  role: string; file: string; url: string; sha256: string; bytes: number; approval_id: string;
  retrieved_at: string | null; last_modified_header: string | null;
}
export interface ReleaseRow {
  release: string; release_date: string; release_date_as_stated: string; last_update_as_stated: string; url: string;
  extract_id: string; months: { key: string; label: string; marker: "r" | "p" }[]; sources: Source[];
  consistency: { table1_row: string; summary_row: string; months: number; equal: boolean }[];
  library: { case_id: string; title: string; href: string } | null;
}
export interface Observed {
  label: string; path: string; naics: string | null; rate: string | null; rate_text: string; month: string;
  column: string; marker: "r" | "p"; table: string; url: string; sha256: string; release: string;
  release_date_as_stated: string;
}
export interface DivergenceCard {
  type: "divergence"; id: string; kind: "group_vs_total" | "subsector_vs_parent"; title: string; month: string;
  month_label: string; gap_pp: string; observed: [Observed, Observed]; adds: string; interpretation: string;
  limitations: string[];
  estimates: { release: string; release_date_as_stated: string; marker: string; row_rate: string | null;
    parent_rate: string | null; relation: string }[];
}
export interface Estimate {
  release: string; release_date_as_stated: string; rate: string | null; rate_text: string; marker: "r" | "p";
  column: string; url: string; naics: string | null;
}
export interface Endpoint {
  release: string; release_date_as_stated: string; rate: string; rate_text: string; marker: "r" | "p"; column: string;
}
export interface RevisionCard {
  type: "revision"; id: string; title: string; row: string; naics: string | null; month: string; month_label: string;
  from: Endpoint; to: Endpoint; revision_pp: string; chain: Estimate[]; adds: string; interpretation: string;
  limitations: string[];
}
export interface ZeroTransition {
  row: string; label: string; month: string; month_label: string; kind: "to_printed_zero" | "from_printed_zero";
  earlier: Endpoint; later: Endpoint; revision_pp: string;
}
export interface QuietParent {
  parent: string; parent_label: string; month: string; month_label: string; release: string;
  release_date_as_stated: string; parent_rate: string; comparisons: number;
}
export interface Divergence {
  order: string; comparisons: number; counts: Record<string, number>; total: number; shown: DivergenceCard[];
  no_direction_parents: QuietParent[];
}
export interface Revisions {
  order: string; counts: Record<string, number>; total: number; shown: RevisionCard[];
  printed_zero_transitions: ZeroTransition[];
}
interface Common {
  view_version: string; scope: string; limitations: string[]; available: string[]; written: false;
  provider_called: false;
}
export interface G17Listing extends Common {
  state: "not_checked" | "checked" | "problem"; detail: string | null;
  check: { check_id: string; checked_at: string; selection: string[] } | null; releases: ReleaseRow[];
  table1: { title: string; unit: string; proportion_label: string; proportion_note: string; naics_note: string } | null;
  divergence: Divergence | null; revisions: Revisions | null; breadth?: Breadth | null;
}
export interface Counts { positive: number; negative: number; printed_zero: number; missing: number }
export interface BreadthMonth {
  month: string; month_label: string; column: string; marker: "r" | "p"; expected: number; counts: Counts;
  groups: Record<"durable" | "nondurable", Counts & { expected: number }>; aggregate_rate: string | null;
  aggregate_rate_text: string; state: "majority_up" | "majority_down" | "no_majority" | "incomplete";
  state_text: string; counts_text: string; aggregate_vs_breadth: boolean;
  shares: { positive: string; negative: string; printed_zero: string } | null;
  members: Record<keyof Counts, string[]>;
}
export interface BreadthSource { release: string; release_date_as_stated: string; url: string; sha256: string;
  table: string }
export interface Switch { label: string; naics: string; from: string; to: string; earlier_rate: string | null;
  later_rate: string | null }
export interface BreadthCard {
  type: "aggregate_vs_breadth" | "breadth_shift" | "breadth_revision"; id: string; month: string;
  month_label: string; title: string;
  source?: BreadthSource; observed?: BreadthMonth[]; change?: Counts;
  earlier?: BreadthSource & { counts_text: string; marker: string; aggregate_rate_text: string };
  later?: BreadthSource & { counts_text: string; marker: string; aggregate_rate_text: string };
  reversals?: Switch[]; printed_zero_transitions?: Switch[]; condition?: string | null; adds: string;
  interpretation: string;
  limitations: string[];
  estimates?: { release: string; release_date_as_stated: string; marker: string; counts_text: string;
    aggregate_rate_text: string; met: boolean }[];
}
export interface Breadth {
  state: "not_checked" | "checked" | "problem"; detail: string | null; definitions: Record<string, unknown>;
  check?: { check_id: string; checked_at: string };
  universe?: { expected: number; durable: number; nondurable: number; aggregate: string; excluded: string };
  latest?: BreadthSource & { state: "computed" | "unavailable"; detail: string | null; months: BreadthMonth[] };
  order?: string; adds?: string; limitations?: string[]; totals?: Record<string, number>; total?: number;
  shown?: BreadthCard[]; counts_unchanged_members_switched?: number;
}
export interface BreadthTables {
  state: "not_checked" | "checked" | "problem"; detail: string | null;
  releases?: (BreadthSource & { state: string; detail: string | null; months: BreadthMonth[];
    shifts: { from: string; to: string; from_label: string; to_label: string; change: Counts; states: string[];
      compared: boolean; shift: boolean }[] })[];
  revisions?: { earlier: BreadthSource; later: BreadthSource; state: string; detail: string | null;
    months: { month: string; month_label: string; earlier_text: string; later_text: string; change: Counts;
      earlier: { state: string; marker: string; aggregate_rate: string | null };
      later: { state: string; marker: string; aggregate_rate: string | null };
      reversals: Switch[]; printed_zero_transitions: Switch[]; coverage_changes: Switch[];
      counts_unchanged_members_switched: boolean; compared: boolean; changed: boolean }[] }[];
}
export interface Comparison {
  kind: string; row: string; row_naics: string | null; parent: string; month: string; column: string; marker: string;
  row_rate: string | null; parent_rate: string | null; relation: "opposing" | "same" | "no_direction" | "unavailable";
  printed_zero_or_missing: string | null; gap_pp: string | null;
}
export interface G17Tables extends Common {
  state: "checked"; check: { check_id: string; checked_at: string; selection: string[] }; releases: (ReleaseRow &
    { comparisons: Comparison[]; counts: Record<string, number> })[];
  months: { key: string; label: string }[];
  revision_rows: { path: string; label: string; naics: string | null; cells: { month: string; estimates: Estimate[];
    steps: (string | null)[] }[] }[];
  breadth?: BreadthTables;
}
export interface G17CheckOutcome {
  view_version: string; check_id: string; created: boolean; extracts_created: number;
  release_results_created: number; revision_results_created: number; releases: string[]; provider_called: false;
  g17_check_created?: boolean;
  breadth?: { check_id: string; created: boolean; release_results_created: number; revision_results_created: number };
}

const SHA = /^[0-9a-f]{64}$/;
const MONTH = /^\d{4}-\d{2}$/;
const RELEASE = /^\d{8}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail : null;
}

function versioned(body: unknown): Record<string, unknown> | null {
  if (typeof body !== "object" || body === null) return null;
  const value = body as Record<string, unknown>;
  return value.view_version === G17_VIEW_VERSION && value.written === false && value.provider_called === false
    ? value : null;
}

const observedOk = (item: Observed, month: string) => item.month === month && typeof item.path === "string" &&
  item.path.length > 0 && SHA.test(item.sha256) && item.url.startsWith("https://www.federalreserve.gov/releases/g17/")
  && item.table === "Table 1" && item.column.startsWith("Monthly rate / ");

/** A breadth month is read only when its counts make up the stated universe and shares or a majority state appear
 * only for a complete month. */
export function breadthMonthOk(month: BreadthMonth): boolean {
  const { positive, negative, printed_zero, missing } = month.counts;
  const total = positive + negative + printed_zero + missing;
  const groups = Object.values(month.groups ?? {});
  return MONTH.test(month.month) && total === month.expected && month.expected === 19 &&
    groups.reduce((sum, group) => sum + group.expected, 0) === month.expected &&
    (missing > 0) === (month.state === "incomplete") && (missing > 0) === (month.shares === null) &&
    (!month.aggregate_vs_breadth || missing === 0);
}

function breadthOk(breadth: Breadth | null | undefined): boolean {
  if (breadth === undefined || breadth === null) return true;
  if (!["not_checked", "checked", "problem"].includes(breadth.state)) return false;
  if (breadth.state !== "checked") return true;
  const latest = breadth.latest, shown = breadth.shown ?? [];
  return !!latest && SHA.test(latest.sha256) && latest.months.every(breadthMonthOk) &&
    shown.length <= (breadth.total ?? 0) && shown.every((card) => MONTH.test(card.month) &&
      (card.observed ?? []).every(breadthMonthOk));
}

/** A listing is read only at this version, with verified-looking releases and cards that cite their own sources. */
export function isG17Listing(body: unknown): boolean {
  const value = versioned(body) as G17Listing | null;
  if (!value || !Array.isArray(value.releases) || !Array.isArray(value.available)) return false;
  if (!["not_checked", "checked", "problem"].includes(value.state)) return false;
  if (value.state !== "checked") return value.divergence === null && value.revisions === null;
  if (!breadthOk(value.breadth)) return false;
  const releases = new Set(value.releases.map((row) => row.release));
  if (!value.releases.every((row) => RELEASE.test(row.release) && SHA.test(row.extract_id) &&
      row.sources.every((source) => SHA.test(source.sha256)))) return false;
  const divergence = value.divergence, revisions = value.revisions;
  if (!divergence || !revisions || divergence.shown.length > divergence.total || revisions.shown.length >
      revisions.total) return false;
  return divergence.shown.every((card) => MONTH.test(card.month) && card.observed.length === 2 &&
      card.observed.every((item) => observedOk(item, card.month) && releases.has(item.release))) &&
    revisions.shown.every((card) => MONTH.test(card.month) && card.chain.length >= 2 &&
      releases.has(card.from.release) && releases.has(card.to.release) &&
      card.chain.every((estimate) => releases.has(estimate.release)));
}

export function isG17Tables(body: unknown): boolean {
  const value = versioned(body) as G17Tables | null;
  if (!value || value.state !== "checked" || !Array.isArray(value.releases) || !Array.isArray(value.revision_rows))
    return false;
  const months = new Set(value.months.map((month) => month.key));
  return value.releases.every((release) => Array.isArray(release.comparisons) &&
      release.comparisons.every((item) => months.has(item.month))) &&
    value.revision_rows.every((row) => row.cells.every((cell) => months.has(cell.month)));
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

export const fetchG17 = (signal: AbortSignal) => read<G17Listing>("/api/insights/g17", signal, isG17Listing);
export const fetchG17Tables = (signal: AbortSignal) =>
  read<G17Tables>("/api/insights/g17/tables", signal, isG17Tables);

export type G17CheckResult =
  | { state: "done"; data: G17CheckOutcome }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string };

/** The explicit local check of all retained releases. A missing reply is "unconfirmed"; nothing is sent again. */
export async function runG17Check(): Promise<G17CheckResult> {
  let response: Response;
  try {
    response = await fetch("/api/insights/g17/checks", {
      method: "POST", body: JSON.stringify({ check_retained_g17: true }),
      headers: { "Content-Type": "application/json", Accept: "application/json", [G17_INSIGHTS_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Reload the page to see whether "
      + "the check was recorded; nothing was sent again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.status >= 500) return { state: "unconfirmed", message: detail(payload) ?? "The server failed." };
  if (!response.ok) return { state: "refused", message: detail(payload) ?? `Refused (${response.status}).` };
  const value = payload as G17CheckOutcome | null;
  if (!value || value.view_version !== G17_VIEW_VERSION || !SHA.test(value.check_id)) {
    return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  }
  return { state: "done", data: value };
}

/** "+0.7%", "−2.1%", "0.0%" (a printed 0.0 keeps its decimal), or "not printed". */
export function rate(text: string | null): string {
  if (text === null) return "not printed";
  const value = Number(text);
  const digits = Math.abs(value).toFixed(1);
  return value > 0 ? `+${digits}%` : value < 0 ? `−${digits}%` : `${digits}%`;
}

/** A difference between rates in percentage points. */
export function points(text: string | null): string {
  if (text === null) return "—";
  const value = Number(text);
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)} pp`;
}

export const MARKER: Record<string, string> = { p: "preliminary", r: "revised" };

export const RELATION: Record<string, string> = {
  opposing: "Opposing", same: "Same direction", no_direction: "No direction (printed 0.0)",
  unavailable: "Not printed",
};

export const REVISION_KIND: Record<string, string> = {
  reversal: "Direction reversed", to_printed_zero: "To printed 0.0", from_printed_zero: "From printed 0.0",
  same_direction: "Same direction, revised", unchanged: "Unchanged", unavailable: "Not printed",
};

/** The last segment of a row path, with the NAICS code where the table prints one. */
export function rowName(path: string, naics: string | null): string {
  const label = path.split(" / ").at(-1) ?? path;
  if (!naics) return label;
  return label.includes("NAICS") ? `${label} (codes ${naics})` : `${label} (NAICS ${naics})`;
}

/** Short labels for the change between two consecutive estimates, for dense tables. */
export const STEP: Record<string, string> = {
  reversal: "reversed", to_printed_zero: "to 0.0", from_printed_zero: "from 0.0", same_direction: "revised",
  unchanged: "unchanged", unavailable: "not printed",
};

export const G17_HREF = "/findings/g17";

/** Breadth classes, their legend labels and the order they are drawn in. */
export const BREADTH_CLASSES: { key: keyof Counts; label: string }[] = [
  { key: "positive", label: "printed up" }, { key: "negative", label: "printed down" },
  { key: "printed_zero", label: "printed 0.0 (no direction)" }, { key: "missing", label: "not printed" },
];

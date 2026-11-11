// Research readiness: one read of what can be frozen prospectively for a publication date, what is missing and the
// next explicit action. The server decides everything; this module shapes the read and refuses a reply whose parts do
// not agree with each other. Checking never downloads, imports, migrates or freezes anything.
import type { Loaded } from "./api";
import { getLifecycle, type StoreState } from "./lifecycle.ts";

export const READINESS_VERSION = "research-readiness-0.2";
export const DATE = /^\d{4}-\d{2}-\d{2}$/;

export type Status = "freeze_ready" | "needs_baseline" | "waiting_for_session" | "concept_only";
const STATUSES = new Set<string>(["freeze_ready", "needs_baseline", "waiting_for_session", "concept_only"]);
export const STATUS_LABEL: Record<Status, string> = {
  freeze_ready: "Ready to freeze", needs_baseline: "Needs a newer baseline",
  waiting_for_session: "Waiting for a session to end", concept_only: "Registry concept only",
};

export interface SnapshotEntry {
  snapshot_id: string; verified: boolean; problem: string | null; retrieved_at: string;
  received_before_now: boolean | null; package_id: string | null; classified_from?: string | null;
  classified_through?: string | null; covers_required_session?: boolean; required_session_status?: string | null;
  history_checked?: boolean; scorable_horizons?: number[];
  horizons?: Record<string, { reference_windows: number; required_reference_windows: number; scorable: boolean;
    reason?: string }>;
}
export interface PackageEntry {
  package_id: string; status: string; received_at: string; coverage: { first: string; last: string } | null;
  received_before_now: boolean; reaches_required_session: boolean; imported_as: string[];
}
export interface Outcome {
  freeze_date_new_york: string; expected_score_anchor: string;
  targets: Record<string, { expected_target: string; counts_after: string }>; state: string; blocks_freeze: false;
  plain: string; path: string;
}
export interface ObservableRow {
  observable_id: string; label: string; kind: "source_bound" | "concept_only"; status: Status; plain: string;
  registry: { source: string | null; unit: string; measurement: string; anchor_policy: string };
  provider: { id: string; series_id: string; name: string; connection: string; freeze_path: string;
    outcome_path: string } | null;
  retained: { snapshots?: SnapshotEntry[]; packages?: PackageEntry[]; newest_classified_date?: string | null };
  freeze: { ready: boolean; baselines: string[]; scorable_horizons: number[]; blockers: string[] };
  outcome: Outcome | null; research: { eligible: false; reasons: string[] }; next_action: string;
}
/** The offline demo's FICTIONAL demonstration series: reported apart, never a registry entry. */
export interface Demonstration {
  fixture: string; version: string; generator: string; timestamp_basis: string; plain: string;
  series: { observable_id: string; provider: string; ticker: string; first_date: string; last_date: string;
    rows: number }[];
  registry_concepts_covered: string[];
}
export interface ProviderSummary {
  provider: string; name: string; status: Exclude<Status, "concept_only">; observables: string[]; baselines: string[];
  scorable_horizons: Record<string, number[]>; composition: string; action: string;
}
export interface Readiness {
  readiness_version: string; lifecycle_version: string;
  answer: { freeze_now: string; outcomes: string; research: string; next_action: string };
  published_date: string; required_session: string; required_session_ended: boolean;
  providers: ProviderSummary[]; observables: ObservableRow[];
  next_actions: { provider: string | null; name: string; status: string; action: string }[];
  research: { measurable_observables: string[]; inclusion_status: string | null; reasons: string[];
    decisions: string[]; plain: string };
  demonstration: Demonstration | null;
  store: StoreState;
  provenance: { checked_at: string; today_new_york: string; required_session_rule: string; freshness_policy: string;
    rules: { version: string; hash: string; min_windows: number };
    calendar: { calendar: string; library: string; library_version: string; exceptions_version: string };
    package_problems: { retrieval: string; problem: string }[]; fixture: string };
  provider_called: false; written: false;
}

const text = (value: unknown) => typeof value === "string" && value.length > 0;

/** Fail-closed: every part must agree with the others, or the reply is not shown. A provider is ready exactly when it
 * names a baseline that every one of its observables can use; a row is ready exactly when it names a baseline; a
 * registry concept has no provider and is never ready; the dates asked about are dates. */
export function isReadiness(value: Record<string, unknown>): boolean {
  const data = value as unknown as Readiness;
  if (data.readiness_version !== READINESS_VERSION || data.provider_called !== false || data.written !== false) return false;
  if (typeof data.answer !== "object" || data.answer === null ||
      !["freeze_now", "outcomes", "research", "next_action"].every((key) => text((data.answer as never)[key]))) return false;
  if (!DATE.test(String(data.published_date)) || !DATE.test(String(data.required_session)) ||
      String(data.required_session) >= String(data.published_date)) return false;
  if (!Array.isArray(data.observables) || !Array.isArray(data.providers) || !Array.isArray(data.next_actions)) return false;
  const rows = new Map<string, ObservableRow>();
  for (const row of data.observables) {
    if (typeof row !== "object" || row === null || !text(row.observable_id) || !STATUSES.has(row.status) ||
        !text(row.plain) || !text(row.next_action) || typeof row.freeze !== "object" || row.freeze === null ||
        !Array.isArray(row.freeze.baselines) || !Array.isArray(row.freeze.blockers)) return false;
    if (row.freeze.ready !== (row.status === "freeze_ready") || row.freeze.ready !== (row.freeze.baselines.length > 0))
      return false;
    const concept = row.kind === "concept_only";
    if (concept !== (row.status === "concept_only") || concept !== (row.provider === null)) return false;
    if (!row.freeze.ready && row.freeze.blockers.length === 0) return false;  // Not ready always says why.
    rows.set(row.observable_id, row);
  }
  if (rows.size !== data.observables.length) return false;
  for (const item of data.providers) {
    if (typeof item !== "object" || item === null || !text(item.action) || !Array.isArray(item.baselines)) return false;
    const mine = data.observables.filter((row) => row.provider?.id === item.provider);
    if (mine.length < 2) return false;  // A source-bound hypothesis needs two distinct observables of one provider.
    if ((item.status === "freeze_ready") !== (item.baselines.length > 0)) return false;
    if (!item.baselines.every((id) => mine.every((row) => row.freeze.baselines.includes(id)))) return false;
  }
  if (typeof data.research !== "object" || data.research === null || !Array.isArray(data.research.measurable_observables) ||
      !data.research.measurable_observables.every((id) => rows.has(id)) || !Array.isArray(data.research.reasons))
    return false;
  const demo = data.demonstration;  // Demonstration series cover no registry entry and are never listed as one.
  if (demo !== null && (typeof demo !== "object" || !Array.isArray(demo.series) ||
      !Array.isArray(demo.registry_concepts_covered) || demo.registry_concepts_covered.length > 0 ||
      demo.series.some((item) => rows.has(item.observable_id)))) return false;
  return data.next_actions.every((item) => typeof item === "object" && item !== null && text(item.action));
}

export function readinessPath(published: string | null): string {
  return "/api/lifecycle/readiness" + (published ? `?published=${encodeURIComponent(published)}` : "");
}

/** One read. ``published`` is a New York date (YYYY-MM-DD), or null for today. */
export const fetchReadiness = (published: string | null, signal: AbortSignal): Promise<Loaded<Readiness>> =>
  getLifecycle<Readiness>(readinessPath(published), signal, isReadiness);

/** Connected observables first (as the registry lists them), then the registry concepts. */
export function groupRows(rows: ObservableRow[]): { connected: ObservableRow[]; concepts: ObservableRow[] } {
  return { connected: rows.filter((row) => row.kind === "source_bound"),
           concepts: rows.filter((row) => row.kind === "concept_only") };
}

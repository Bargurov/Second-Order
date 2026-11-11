// The administrator's API (admin-api-0.4, docs/admin-user-contract.md section 10, docs/account-binding-contract.md,
// docs/news-usage-contract.md and docs/news-stories-contract.md; the News desk's payloads are in newsDesk.ts).
// Admin-only payloads: models, Effort, timings, usage, planning estimates and usage-derived costs live here and never in
// src/contracts/user.ts. Reads are plain GETs; every write is one explicit POST with this page's admin header. Every
// read and write names the administrator this page was opened for, so a page left open after another sign-in in this
// browser is refused (account_changed) instead of acting or reading as the account now signed in. Nothing retries.
import { useEffect, useState } from "react";
import { ACCOUNT_HEADER } from "../contracts/user.ts";

export const ADMIN_CONTRACT = "admin-api-0.4";
export const ADMIN_HEADER = "X-Second-Order-Admin";

let boundAccount: string | null = null;
/** The administrator this page was opened for (AdminApp sets it from the session before any screen reads). */
export function bindAdminAccount(account: string | null): void {
  boundAccount = account;
}
export const accountBinding = (): Record<string, string> =>
  (boundAccount === null ? {} : { [ACCOUNT_HEADER]: boundAccount });

export interface Balance {
  available: number; held: number; granted: number; corrections: number; charged: number; reconciles: boolean;
}
export interface Daily {
  timezone: string; day: string; limit: number | null; used: number; remaining: number | null; resets_at: string;
}
export interface RegistrationDecision { decision: "approved" | "rejected"; decided_at: string; decided_by: string;
  reason: string }
export interface AdminUser {
  user_id: string; username: string; display_name: string; role: "admin" | "user"; active: boolean;
  /** pending or rejected: a registration without an approval; otherwise active or disabled, as before. */
  status: "pending" | "rejected" | "active" | "disabled";
  registration: { submitted_at: string; note: string; decision: RegistrationDecision | null } | null;
  created_at: string; created_by: string; credits?: Balance; daily?: Daily;
  /** Users only: whether any grant or correction was ever recorded, whatever the balance now. */
  allocated?: boolean;
}
export interface LedgerEntry {
  entry_id: number; user_id: string; kind: "grant" | "correction" | "hold" | "release" | "settle"; amount: number;
  attempt_id: string | null; actor: string; reason: string; at: string; idempotency_key: string;
}
export interface Policy {
  policy_version: string; flow: string; model: string; efforts: Record<string, { extra_credits: number }>;
  credits: { base: number; per_1k_input_tokens: number; per_1k_output_tokens: number };
  max_request_usd: number; quote_valid_seconds: number; settlement: string; created_at: string; created_by: string;
  reason: string;
}
/** A draft policy's quotes for the synthetic examples; nothing is recorded by a preview. */
export interface PolicyPreview {
  policy: Omit<Policy, "policy_version" | "created_at" | "created_by" | "reason">; size_note: string; recorded: false;
  examples: { example: string; label: string; characters: number;
              quotes: { effort: string; credits: number; input_tokens_assumed: number; planning_estimate_usd: number;
                        refused_over_budget: boolean }[] }[];
}
/** The operator's selected terms as presets. Choosing one fills a draft or a form and records nothing. */
export interface PolicyPreset {
  preset: string; label: string; note: string; credits: Policy["credits"]; efforts: Policy["efforts"];
}
export interface AllocationPreset { preset: string; label: string; note: string; credits: number; daily_limit: number }
export interface PolicyView {
  current: Policy | null; versions: Policy[]; verified_efforts: Record<string, string[]>; effort_source: string;
  output_bound_tokens: number; settlement: string; formula: string; presets: PolicyPreset[];
}
export interface Entitlement {
  attempt_id: string; quote_id: string; credits_quoted: number; credits_charged: number | null; quota_day: string;
  quota_timezone: string; state: "held" | "needs_review" | "charged" | "returned"; sent_recorded_at: string | null;
  quote: { policy_version: string; issued_at: string; expires_at: string; planning_estimate_usd: number;
           input_tokens_assumed: number; max_tokens: number };
  worker_active: boolean; observed: Observed;
}
/** The state an administrator decides on; a resolution repeats it and is refused if it changed. */
export interface Observed { sent_at: string | null; outcome: string | null }
export interface ActionRow {
  request_id: string; capture_id: string; action: "prepare" | "local_mock" | "provider_call" | "unreadable";
  charge_kind?: string; problem?: string;
  requested_by?: { kind: "operator" } | { kind: "user"; user_id: string; username: string | null;
                                          display_name: string | null };
  request_version?: string; model?: string; effort?: string; max_tokens?: number; attempt_state?: string;
  outcome?: string | null;
  timing?: { prepared_at: string; reserved_at: string | null; sent_at: string | null; received_at: string | null;
             elapsed_seconds: number | null; measured_by: string; unavailable: string[] };
  usage?: Record<string, number> | null; http_status?: number | null; provider_request_id?: string | null;
  planning_estimate_usd?: number | null; planning_estimate_basis?: string; usage_cost_usd?: number | null;
  usage_cost_basis?: string | null; entitlement?: Entitlement | null;
}
export interface Hold extends ActionRow { user_id: string; attempt_id: string; credits: number; reserved_at: string;
  resolvable: boolean; observed: Observed; worker_active: boolean }

/** The usage limits, all whole numbers the administrator chose (docs/news-usage-contract.md, section 3). */
export const ACCOUNT_LIMITS = ["searches_per_day", "imports_per_day", "sources_per_day", "preparations_per_day",
  "max_sources", "max_source_bytes", "requests_per_minute", "concurrent_requests"] as const;
export const SERVER_LIMITS = ["publication_fetches_per_day", "refreshes_per_day", "refresh_cooldown_seconds"] as const;
export type AccountLimit = (typeof ACCOUNT_LIMITS)[number];
export type ServerLimit = (typeof SERVER_LIMITS)[number];
export interface UsageLimits { account: Record<AccountLimit, number>; server: Record<ServerLimit, number> }
export interface UsagePolicy extends UsageLimits {
  policy_version: string; created_at: string; created_by: string; reason: string;
}
export interface UsagePolicyView {
  current: UsagePolicy | null; versions: UsagePolicy[];
  bounds: { account: Record<AccountLimit, { min: number; max: number }>;
            server: Record<ServerLimit, { min: number; max: number }> };
}
/** Today's count of one operation; limit and remaining are null without a usage policy. */
export interface UsageCount {
  operation: "search" | "import" | "source" | "preparation"; label: string; limit: number | null; used: number;
  remaining: number | null;
}
export interface Allowance { used: number; limit: number | null }
/** Local counts of what this server accepted and requested today. They are not billing and verify no cost. */
export interface UsageOverview {
  policy: UsagePolicy | null; day: string; timezone: string; resets_at: string;
  accounts: { user_id: string; operations: UsageCount[]; storage: { sources: Allowance; source_bytes: Allowance } }[];
  server: { publication_fetches: Allowance; refreshes: Allowance; last_refresh_started_at: string | null;
            next_refresh_allowed_at: string | null };
}

export type AdminRead<T> = { state: "loading" } | { state: "ready"; data: T } | { state: "error"; message: string };
export type AdminWrite<T> = { state: "saved"; data: T } | { state: "refused" | "unconfirmed"; message: string };

const UNREACHABLE = "The server did not answer. Nothing was retried; read the page again before acting.";

function message(body: unknown, status: number): string {
  const detail = typeof body === "object" && body !== null ? (body as { detail?: unknown }).detail : null;
  return typeof detail === "string" ? detail : `Unexpected reply (${status}).`;
}

export async function adminGet<T>(path: string, signal?: AbortSignal): Promise<AdminRead<T>> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json", ...accountBinding() }, signal,
                                   credentials: "same-origin" });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: "error", message: message(body, response.status) };
  if ((body as { contract?: unknown } | null)?.contract !== ADMIN_CONTRACT) {
    return { state: "error", message: "The reply is not an administrator payload." };
  }
  return { state: "ready", data: body as T };
}

export async function adminPost<T>(path: string, payload: object): Promise<AdminWrite<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST", credentials: "same-origin", body: JSON.stringify(payload),
      headers: { Accept: "application/json", "Content-Type": "application/json", [ADMIN_HEADER]: "1", ...accountBinding() },
    });
  } catch {
    return { state: "unconfirmed", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { state: response.status >= 500 ? "unconfirmed" : "refused", message: message(body, response.status) };
  }
  return { state: "saved", data: body as T };
}

export function useAdmin<T>(path: string, version: number): AdminRead<T> {
  const [state, setState] = useState<AdminRead<T>>({ state: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ state: "loading" });
    adminGet<T>(path, controller.signal).then((read) => { if (!controller.signal.aborted) setState(read); },
                                               () => undefined);
    return () => controller.abort();
  }, [path, version]);
  return state;
}

/** One idempotency key per form submission: repeating the same submission makes no second ledger entry. */
export const newKey = () => `key-${crypto.randomUUID().replace(/-/g, "")}`;

export const adminPaths = {
  users: "/api/admin/users",
  registrations: "/api/admin/registrations",
  decision: (userId: string) => `/api/admin/registrations/${encodeURIComponent(userId)}/decision`,
  policyPreview: "/api/admin/policy/preview",
  user: (userId: string, action: "status" | "credits" | "daily-limit") =>
    `/api/admin/users/${encodeURIComponent(userId)}/${action}`,
  ledger: (userId?: string) => userId ? `/api/admin/ledger?user_id=${encodeURIComponent(userId)}` : "/api/admin/ledger",
  holds: "/api/admin/holds",
  resolve: (attemptId: string) => `/api/admin/attempts/${encodeURIComponent(attemptId)}/resolve`,
  policy: "/api/admin/policy",
  settings: "/api/admin/settings",
  actions: "/api/admin/actions",
  ownership: "/api/admin/ownership",
  usagePolicy: "/api/admin/usage-policy",
  usage: "/api/admin/usage",
};

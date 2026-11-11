// How the Admin screens say amounts, times and missing values. A missing value is said to be missing, never shown as
// zero: an unreported usage is "Not reported", an uncomputable cost "Unknown".
import {
  ACCOUNT_LIMITS, SERVER_LIMITS, type AccountLimit, type ActionRow, type AdminUser, type Allowance, type Policy,
  type PolicyPreset, type ServerLimit, type UsageLimits,
} from "./adminApi.ts";

export const UNKNOWN_COST = "Unknown";
export const NOT_REPORTED = "Not reported";
export const NOT_RECORDED = "Not recorded";

export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN_COST;
  return `$${value.toFixed(value !== 0 && Math.abs(value) < 0.01 ? 6 : 4)}`;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_RECORDED;
  return value < 1 ? `${Math.round(value * 1000)} ms` : `${value.toFixed(1)} s`;
}

export function usage(value: Record<string, number> | null | undefined): string {
  if (!value || (value.input_tokens === undefined && value.output_tokens === undefined)) return NOT_REPORTED;
  const parts = [`${value.input_tokens?.toLocaleString("en-US") ?? "?"} in`,
    `${value.output_tokens?.toLocaleString("en-US") ?? "?"} out`];
  if (value.cache_read_input_tokens) parts.push(`${value.cache_read_input_tokens.toLocaleString("en-US")} cached`);
  return parts.join(" · ");
}

export function when(iso: string | null | undefined): string {
  if (!iso) return NOT_RECORDED;
  const time = new Date(iso);
  return Number.isNaN(time.getTime()) ? iso : `${time.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export function signedCredits(amount: number): string {
  return amount > 0 ? `+${amount}` : String(amount);
}

export const ACTION_LABEL: Record<ActionRow["action"], string> = {
  prepare: "Prepared · local, no charge", local_mock: "Local mock · $0, no provider", provider_call: "Provider call",
  unreadable: "Unreadable record",
};

export const ENTITLEMENT_LABEL: Record<string, string> = {
  held: "Held (in flight)", needs_review: "Needs review", charged: "Charged", returned: "Returned",
};

export function requester(row: ActionRow): string {
  if (!row.requested_by) return "—";
  return row.requested_by.kind === "operator" ? "Operator"
    : `${row.requested_by.display_name ?? "Unknown account"} (${row.requested_by.username ?? row.requested_by.user_id})`;
}

export function credits(row: ActionRow): string {
  const entitlement = row.entitlement;
  if (!entitlement) return row.requested_by?.kind === "operator" ? "Operator: no credits" : "—";
  const charged = entitlement.credits_charged === null ? "" : `, ${entitlement.credits_charged} charged`;
  return `${entitlement.credits_quoted} quoted${charged} · ${ENTITLEMENT_LABEL[entitlement.state] ?? entitlement.state}`;
}

export const ADMIN_SCREENS = ["users", "registrations", "credits", "actions", "policy", "usage", "news"] as const;
export type AdminScreen = (typeof ADMIN_SCREENS)[number];
export const SCREEN_LABEL: Record<AdminScreen, string> = {
  users: "Users", registrations: "Registrations", credits: "Credits & holds", actions: "Actions",
  policy: "Policy & settings", usage: "Usage & limits", news: "News desk",
};

export const STATUS_LABEL: Record<"pending" | "rejected" | "active" | "disabled", string> = {
  pending: "Registration waiting", rejected: "Registration rejected", active: "Active", disabled: "Inactive",
};

/** A preset's points at each Effort it sets, in order: "low 10 · medium 15 · …". */
export function presetPoints(preset: PolicyPreset): string {
  return Object.entries(preset.efforts).map(([effort, terms]) =>
    `${effort} ${preset.credits.base + terms.extra_credits}`).join(" · ");
}

export interface PolicyDraft {
  enabled: Record<string, string>;
  rates: { base: string; per_1k_input_tokens: string; per_1k_output_tokens: string; max_request_usd: string;
           quote_valid_seconds: string };
}

/** A draft filled from a preset: its rates and the Effort extras this model accepts. A preset has no per-request
 * planning limit or quote validity, so those keep what the administrator typed, else the active version's value,
 * else stay empty for them to decide. */
export function presetDraft(preset: PolicyPreset, verified: readonly string[], current: Policy | null,
                            typed: PolicyDraft["rates"]): PolicyDraft {
  const kept = (field: "max_request_usd" | "quote_valid_seconds") =>
    typed[field] !== "" ? typed[field] : current ? String(current[field]) : "";
  return {
    enabled: Object.fromEntries(Object.entries(preset.efforts).filter(([effort]) => verified.includes(effort))
      .map(([effort, terms]) => [effort, String(terms.extra_credits)])),
    rates: { base: String(preset.credits.base), per_1k_input_tokens: String(preset.credits.per_1k_input_tokens),
             per_1k_output_tokens: String(preset.credits.per_1k_output_tokens),
             max_request_usd: kept("max_request_usd"), quote_valid_seconds: kept("quote_valid_seconds") },
  };
}

export const LIMIT_LABEL: Record<AccountLimit | ServerLimit, string> = {
  searches_per_day: "Searches per day", imports_per_day: "Publication imports per day",
  sources_per_day: "New sources per day", preparations_per_day: "Prepared analyses per day",
  max_sources: "Sources an account may hold", max_source_bytes: "Source text an account may hold (bytes)",
  requests_per_minute: "Requests per minute (protective)", concurrent_requests: "Requests in progress (protective)",
  publication_fetches_per_day: "Publication page fetches per day", refreshes_per_day: "Feed refreshes per day",
  refresh_cooldown_seconds: "Seconds between feed refreshes",
};

/** A usage-limits form: every field as typed, empty until the administrator types a value or copies a version. */
export type UsageForm = Record<AccountLimit | ServerLimit, string>;

export const emptyUsageForm = (): UsageForm =>
  Object.fromEntries([...ACCOUNT_LIMITS, ...SERVER_LIMITS].map((name) => [name, ""])) as UsageForm;

/** A published version's values, to start a new version from them. */
export function usageFormFrom(limits: UsageLimits): UsageForm {
  return { ...Object.fromEntries(ACCOUNT_LIMITS.map((name) => [name, String(limits.account[name])])),
           ...Object.fromEntries(SERVER_LIMITS.map((name) => [name, String(limits.server[name])])) } as UsageForm;
}

/** The limits a form publishes. A field that is not a whole number (empty included) is sent as null, which the server
 * refuses, so nothing is ever published as zero by default. */
export function usageDraft(form: UsageForm): UsageLimits {
  const whole = (value: string) => /^[0-9]+$/.test(value.trim()) ? Number(value.trim()) : null;
  return { account: Object.fromEntries(ACCOUNT_LIMITS.map((name) => [name, whole(form[name])])),
           server: Object.fromEntries(SERVER_LIMITS.map((name) => [name, whole(form[name])])) } as UsageLimits;
}

/** "3 of 10", or "3 · no limit set" without a usage policy. */
export function allowance({ used, limit }: Allowance, unit = ""): string {
  const amount = (value: number) => `${value.toLocaleString("en-US")}${unit}`;
  return limit === null ? `${amount(used)} · no limit set` : `${amount(used)} of ${amount(limit)}`;
}

/** The initial allocation is offered only to an approved, active user with nothing allocated and no daily limit. */
export function offersInitialAllocation(user: AdminUser): boolean {
  return user.role === "user" && user.status === "active" && user.allocated === false && user.daily?.limit === null;
}

/** A registration that was never approved (waiting or rejected): the store records no credits, limit or records for
 * it, so its zero balance is not an allocation to show. */
export function unapproved(user: AdminUser): boolean {
  return user.status === "pending" || user.status === "rejected";
}

/** What waits for the administrator, from the users list alone: registrations waiting for a decision, and approved
 * accounts the initial allocation still applies to (nothing ever allocated, no daily limit). */
export function needsAttention(users: readonly AdminUser[]): { waiting: AdminUser[]; unallocated: AdminUser[] } {
  return { waiting: users.filter((user) => user.status === "pending"), unallocated: users.filter(offersInitialAllocation) };
}

/** "1 registration" / "2 registrations". */
export function count(amount: number, one: string, many: string): string {
  return `${amount} ${amount === 1 ? one : many}`;
}

/** An account's display name from the users list; an account the list does not hold is named by its recorded ID. */
export function nameOf(userId: string, users: readonly AdminUser[]): string {
  return users.find((user) => user.user_id === userId)?.display_name ?? userId;
}

/** The Users screen with one account's panel open. */
export const manageHref = (username: string): string => `/admin?manage=${encodeURIComponent(username)}`;

/** The username a ?manage= address names, if any. URLSearchParams never throws on malformed escapes. */
export function manageTarget(search: string): string | null {
  return new URLSearchParams(search).get("manage") || null;
}

/** The Admin screen at a path (/admin is Users), or null for every operator page. */
export function adminScreen(pathname: string): AdminScreen | null {
  const match = /^\/admin(?:\/([a-z]+))?\/?$/.exec(pathname);
  if (!match) return null;
  const screen = match[1] ?? "users";
  return (ADMIN_SCREENS as readonly string[]).includes(screen) ? screen as AdminScreen : null;
}

/**
 * event-inbox.ts — fail-closed consumer of automatic-event-inbox-v1.
 *
 * The inbox GET (/news/inbox) is local-state-only on the backend; this module
 * is the frontend's contract boundary.  `parseInboxPayload` accepts ONLY a
 * payload that matches the captured producer output pinned in
 * fixtures/automatic-event-inbox-v1.json (deep-equal against the live route
 * by tests/test_event_inbox_route_boundary.py) and refuses everything else —
 * a malformed inbox must never render as a plausible inbox.
 *
 * Types are derived from the captured payload, never from field names.
 */

export const LIFECYCLES = ["NEW", "DEVELOPING", "WATCH", "RESOLVED"] as const;
export type Lifecycle = (typeof LIFECYCLES)[number];

export const MATERIAL_CHANNELS = [
  "GROWTH", "INFLATION", "RATES", "LIQUIDITY", "CREDIT", "CURRENCY",
  "TRADE", "SUPPLY_CHAIN", "FISCAL_POLICY", "REGULATION",
  "CORPORATE_EARNINGS", "TECHNOLOGY_PRODUCTIVITY", "ENERGY_COMMODITIES",
  "GEOPOLITICAL_RISK",
] as const;
export type MaterialChannel = (typeof MATERIAL_CHANNELS)[number];

/** Permanent surfacing non-claim — rendered on the page at all times. */
export const INBOX_NON_CLAIM =
  "Events are surfaced through explicit source, identity and economic-channel rules. " +
  "Inclusion is not a prediction of price direction, significance or tradeability.";

/** Permanent absence disclosure — rendered on the page at all times. */
export const INBOX_ABSENCE_NOTE =
  "Absence from the inbox does not prove that an event is economically irrelevant.";

export interface InboxSource {
  name: string;
  tier: string;
  official: boolean;
}

export interface InboxAnalysisTarget {
  headline: string;
  context: string;
}

export interface InboxEvent {
  event_id: string;
  cluster_id: number;
  headline: string;
  event_summary: string | null;
  first_seen_at: string | null;
  last_updated_at: string | null;
  lifecycle: Lifecycle;
  source_count: number;
  sources: InboxSource[];
  official_source_present: boolean;
  event_family: string | null;
  event_type: string | null;
  material_channels: MaterialChannel[];
  why_surfaced: string[];
  known_unknowns: string[];
  analysis_target: InboxAnalysisTarget;
  availability_status: "AVAILABLE" | "PARTIAL";
  missing_reason: string | null;
}

export interface InboxCounts {
  clusters_total: number;
  surfaced: number;
  beyond_window: number;
  excluded_no_material_channel: number;
  malformed_rows: number;
  by_lifecycle: Record<Lifecycle, number>;
}

export interface InboxPayload {
  contract: "automatic-event-inbox-v1";
  generated_from: string;
  as_of: string;
  availability: "AVAILABLE" | "UNAVAILABLE";
  events: InboxEvent[];
  counts: InboxCounts;
  limitations: string[];
  non_claim: string;
}

const TOP_FIELDS = [
  "contract", "generated_from", "as_of", "availability",
  "events", "counts", "limitations", "non_claim",
] as const;

const EVENT_FIELDS = [
  "event_id", "cluster_id", "headline", "event_summary",
  "first_seen_at", "last_updated_at", "lifecycle",
  "source_count", "sources", "official_source_present",
  "event_family", "event_type", "material_channels",
  "why_surfaced", "known_unknowns", "analysis_target",
  "availability_status", "missing_reason",
] as const;

// Field-name tokens that would smuggle a ranking or a directional readout
// into the contract.  Mirrors the backend validator.
const BANNED_FIELD_TOKENS = [
  "score", "priority", "urgency", "conviction", "importance",
  "impact", "direction", "buy", "sell", "tradeab", "signal",
] as const;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}

function nullableString(v: unknown): boolean {
  return v === null || typeof v === "string";
}

function exactKeys(obj: Record<string, unknown>, fields: readonly string[]): boolean {
  const keys = Object.keys(obj);
  return keys.length === fields.length && fields.every((f) => f in obj);
}

function hasBannedField(node: unknown): boolean {
  if (Array.isArray(node)) return node.some(hasBannedField);
  if (!isRecord(node)) return false;
  for (const key of Object.keys(node)) {
    const lk = key.toLowerCase();
    if (BANNED_FIELD_TOKENS.some((t) => lk.includes(t))) return true;
    if (hasBannedField(node[key])) return true;
  }
  return false;
}

function validEvent(raw: unknown): raw is InboxEvent {
  if (!isRecord(raw) || !exactKeys(raw, EVENT_FIELDS)) return false;
  if (typeof raw.event_id !== "string" || raw.event_id === "") return false;
  if (typeof raw.cluster_id !== "number") return false;
  if (typeof raw.headline !== "string" || raw.headline === "") return false;
  if (!nullableString(raw.event_summary)) return false;
  if (!nullableString(raw.first_seen_at)) return false;
  if (!nullableString(raw.last_updated_at)) return false;
  if (!(LIFECYCLES as readonly string[]).includes(raw.lifecycle as string)) return false;
  if (typeof raw.source_count !== "number") return false;
  if (!Array.isArray(raw.sources)) return false;
  for (const s of raw.sources) {
    if (!isRecord(s)) return false;
    if (typeof s.name !== "string" || typeof s.tier !== "string") return false;
    if (typeof s.official !== "boolean") return false;
  }
  if (typeof raw.official_source_present !== "boolean") return false;
  if (!nullableString(raw.event_family)) return false;
  if (!nullableString(raw.event_type)) return false;
  const channels = raw.material_channels;
  if (!isStringArray(channels) || channels.length === 0) return false;
  if (!channels.every((c) => (MATERIAL_CHANNELS as readonly string[]).includes(c))) return false;
  if (!isStringArray(raw.why_surfaced) || raw.why_surfaced.length === 0) return false;
  if (!isStringArray(raw.known_unknowns)) return false;
  const target = raw.analysis_target;
  if (!isRecord(target) || !exactKeys(target, ["headline", "context"])) return false;
  if (typeof target.headline !== "string" || typeof target.context !== "string") return false;
  if (raw.availability_status !== "AVAILABLE" && raw.availability_status !== "PARTIAL") return false;
  if (!nullableString(raw.missing_reason)) return false;
  if (raw.availability_status === "PARTIAL" &&
      (typeof raw.missing_reason !== "string" || raw.missing_reason === "")) return false;
  return true;
}

function validCounts(raw: unknown, events: InboxEvent[]): raw is InboxCounts {
  if (!isRecord(raw)) return false;
  const numeric = ["clusters_total", "surfaced", "beyond_window",
    "excluded_no_material_channel", "malformed_rows"] as const;
  if (!exactKeys(raw, [...numeric, "by_lifecycle"])) return false;
  for (const f of numeric) {
    if (typeof raw[f] !== "number") return false;
  }
  const byLc = raw.by_lifecycle;
  if (!isRecord(byLc) || !exactKeys(byLc, LIFECYCLES)) return false;
  let sum = 0;
  for (const lc of LIFECYCLES) {
    const n = byLc[lc];
    if (typeof n !== "number") return false;
    sum += n;
  }
  // Cross-section reconciliation: the counts must describe THESE events.
  if (raw.surfaced !== events.length || sum !== events.length) return false;
  const accounted = events.length + (raw.beyond_window as number) +
    (raw.excluded_no_material_channel as number) + (raw.malformed_rows as number);
  if (raw.clusters_total !== accounted) return false;
  for (const lc of LIFECYCLES) {
    if (byLc[lc] !== events.filter((e) => e.lifecycle === lc).length) return false;
  }
  return true;
}

/**
 * Validate and narrow an unknown response into an InboxPayload.
 * Returns null on ANY violation — the caller must render an explicit
 * refusal, never a partial inbox.
 */
export function parseInboxPayload(raw: unknown): InboxPayload | null {
  if (!isRecord(raw) || !exactKeys(raw, TOP_FIELDS)) return null;
  if (raw.contract !== "automatic-event-inbox-v1") return null;
  if (typeof raw.generated_from !== "string") return null;
  if (typeof raw.as_of !== "string" || raw.as_of === "") return null;
  if (raw.availability !== "AVAILABLE" && raw.availability !== "UNAVAILABLE") return null;
  if (!Array.isArray(raw.events)) return null;
  const events: InboxEvent[] = [];
  for (const ev of raw.events) {
    if (!validEvent(ev)) return null;
    events.push(ev);
  }
  // Publication order: (last_updated_at, cluster_id) non-increasing.
  for (let i = 1; i < events.length; i++) {
    const a = events[i - 1]!;
    const b = events[i]!;
    const aKey = a.last_updated_at ?? "";
    const bKey = b.last_updated_at ?? "";
    if (aKey < bKey || (aKey === bKey && a.cluster_id < b.cluster_id)) return null;
  }
  if (!validCounts(raw.counts, events)) return null;
  if (!isStringArray(raw.limitations)) return null;
  if (!raw.limitations.includes(INBOX_ABSENCE_NOTE)) return null;
  if (raw.non_claim !== INBOX_NON_CLAIM) return null;
  if (hasBannedField(raw)) return null;
  return raw as unknown as InboxPayload;
}

/** Group events under the four workflow states, preserving payload order. */
export function groupByLifecycle(
  events: InboxEvent[],
): Record<Lifecycle, InboxEvent[]> {
  const groups: Record<Lifecycle, InboxEvent[]> = {
    NEW: [], DEVELOPING: [], WATCH: [], RESOLVED: [],
  };
  for (const ev of events) groups[ev.lifecycle].push(ev);
  return groups;
}

/**
 * Cache-only / provider-only-on-action contract: rendering the inbox must
 * NEVER start an analysis (an analysis is a provider call; it is an explicit
 * per-event user action).  Exported as an always-false predicate so the
 * invariant stays unit-tested and a future render-triggered analysis fails
 * the test — same pattern as shouldAutoRefreshOnRender.
 */
export function shouldAutoAnalyzeOnLoad(): boolean {
  return false;
}

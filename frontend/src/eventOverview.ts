// The private event overview: one Inbox entry or saved capture with its source, saved headline triage, draft and
// review, and market context, as the server read them from local records. Reads only; every action links to the
// existing workflow that performs it.
import type { Loaded } from "./api";
import type { AnalysisEntry } from "./analyses.ts";
import type { EventDefinition, EventView } from "./eventContext.ts";
import type { InboxItem } from "./inbox";

export const OVERVIEW_VERSION = "event-overview-0.1";
export type OverviewKind = "inbox" | "capture";

export interface TriageMode {
  mode: "simulated" | "paid";
  mode_note: string;
  status: "current" | "earlier_version" | "unresolved" | "none";
  result: { category: string; event_type: string | null; summary: string } | null;
  provenance: {
    triage_id: string; mode: string; config: { model: string; prompt_version: string; schema_version: string };
    current_config: boolean; received_at: string; request_sha256: string; response_id: string | null;
    request_id: string | null; validation_policy: string;
    revalidation: { validation_policy: string; revalidated_at: string; original_outcome: string;
                    original_validation_policy: string; original_message: string | null } | null;
  } | null;
  claim: { state: string; triage_id: string | null; detail: string | null } | null;
  other_versions_with_results: number;
}

export interface TriageRelation {
  mode: string;
  relation: string;
  label: string;
  reason: string;
  others: { item_id: string; title: string | null; same_version_held_now: boolean }[];
  scope_checked: boolean;
  provenance: TriageMode["provenance"];
}

export interface TriageSection {
  state: "results" | "none" | "no_entry" | "no_origin" | "origin_unreadable" | "origin_not_held" | "not_offered";
  fingerprint: string | null;
  modes: TriageMode[];
  relations: TriageRelation[];
  unreadable_requests: unknown[];
}

export interface OriginLink {
  state: "none" | "verified" | "unreadable";
  problem: string | null;
  link: { capture_id: string; recorded_at: string; statement: string;
          inbox: { item_id: string; content_sha256: string; version: number | null; versions: number; location: string;
                   title: string; link: string; feed_timestamp_raw: string | null };
          form: { headline_matches: boolean; source_url_matches: boolean } } | null;
  entry: { held: boolean; location: string | null; current_content_sha256: string | null;
           same_version_as_current: boolean; title_now: string | null } | null;
}

export interface LinkedCapture {
  capture_id: string;
  origin: OriginLink;
  headline: string | null;
  captured_at: string | null;
  published_at_as_supplied?: string;
  analysis: { state: string; outcome: string | null; review: AnalysisEntry["review"] | null; detail: string | null } | null;
  problem: string | null;
}

export interface AnalysisSection {
  state: "listed" | "none" | "incomplete" | "awaiting_publication" | "unreadable" | "linked";
  draft_id?: string | null;
  entry?: AnalysisEntry | null;
  mode?: string | null;
  detail?: string | null;
  siblings?: LinkedCapture[];
  captures?: LinkedCapture[];
  unreadable_links?: string[];
}

export interface MarketSection {
  state: "unsupported" | "unreadable" | "needs_date" | "stale_confirmation" | "complete" | "partial" | "no_data";
  href: string | null;
  problem: string | null;
  event: (Pick<EventDefinition, "key" | "supported" | "family_label" | "outside" | "context" | "suggestion" |
                "suggestion_problem" | "problem"> & {
           confirmation_stale: { version: number; context_date: string; title: string } | null }) | null;
  view: EventView | null;
  plan: { needed_sessions: number; held_sessions: number; missing_sessions: number; future_sessions: number;
          requests: number } | null;
}

export interface InboxSource {
  kind: "inbox"; id: string; key: string; held: boolean; location: string | null; entry: InboxItem | null;
  content_sha256: string | null; note: string; full_text_element?: boolean;
  versions: { number: number; content_sha256: string; title: string; link: string; feed_timestamp_raw: string | null;
              first_seen_at: string; last_seen_at: string; current: boolean }[];
}

export interface CaptureSource {
  kind: "capture"; id: string; key: string; note: string; source_text: string; origin: OriginLink;
  event: { headline: string; source_url: string; published_at: string };
  times: { published_at: string; published_at_as_supplied: string; captured_at: string; captured_at_note: string;
           published_at_note: string };
  source: { sha256: string; bytes: number };
  request: { sha256: string; bytes: number; prompt_version: string };
}

export interface EventOverview {
  overview_version: string;
  kind: OverviewKind;
  id: string;
  title: string;
  not_a_dossier: string;
  provider_called: false;
  source: InboxSource | CaptureSource;
  triage: TriageSection;
  analysis: AnalysisSection;
  market: MarketSection;
  history?: ProcessingHistory;
}

export const HISTORY_VERSION = "event-history-0.1";
export type HistoryStep = "source" | "triage" | "analysis" | "review" | "use";

/** Kept apart: the planning estimate made before sending (whole request), the cost derived from reported usage, and
 * billing, which no local record verifies. A null amount is unknown, never zero. */
export interface HistoryCost {
  estimate_usd: number | null;
  usage_usd: number | null;
  billing: "not_verified" | null;
  basis: string;
}

export interface HistoryRow {
  step: HistoryStep;
  at: string | null;
  state: string;
  tone: "info" | "done" | "warn";
  label: string;
  detail: string | null;
  version: number | null;
  href: string | null;
  cost: HistoryCost | null;
  current?: boolean;
  retrievals?: number;
  role?: "entry" | "context";
  mode?: string;
  triage_id?: string;
  /** "research": a row of the evidence-first research analysis, not of the hypothesis draft. */
  kind?: "research";
  request_id?: string;
  /** A research row that records a response (or failure); a prepared request never has it. */
  result?: boolean;
}

/** What was done with one event, as dated steps from the records each step keeps. */
export interface ProcessingHistory {
  history_version: string;
  provider_called: false;
  state: "not_processed" | "processed" | "needs_attention";
  summary: { retrievals: number; versions: number; model_triage: number; simulated_triage: number;
             triage_requests: number; captures: number; drafts: number; reviews: number; frozen: number;
             uncertain: number; failed: number; research_requests?: number; research_results?: number;
             research_reviews?: number };
  steps: { step: HistoryStep; rows: HistoryRow[] }[];
  limitations: string[];
}

export const overviewHref = (kind: OverviewKind, id: string) => `/events/${kind}/${encodeURIComponent(id)}`;
/** A saved event's evidence-first research analysis page (see researchAnalysis). */
export const researchHref = (captureId: string) => `/events/capture/${encodeURIComponent(captureId)}/research`;

/** The existing review screen for a draft, with the way back to this overview. */
export const reviewFromOverview = (draftId: string, kind: OverviewKind, id: string) =>
  `/?draft=${draftId}&from=${encodeURIComponent(overviewHref(kind, id))}`;

/** One overview, as the server read it. A refusal keeps the server's own explanation. */
export async function fetchOverview(kind: OverviewKind, id: string, signal?: AbortSignal): Promise<Loaded<EventOverview>> {
  let response: Response;
  try {
    response = await fetch(`/api/events/${kind}/${encodeURIComponent(id)}`, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: "The local API did not answer. Start it with: python -m second_order serve" };
  }
  const body: unknown = await response.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  const message = typeof detail === "string" ? detail : `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  const overview = body as EventOverview | null;
  if (overview?.overview_version !== OVERVIEW_VERSION || overview.kind !== kind || overview.id !== id ||
      overview.provider_called !== false || (overview.history !== undefined &&
        (overview.history.history_version !== HISTORY_VERSION || overview.history.provider_called !== false ||
         !Array.isArray(overview.history.steps)))) {
    return { state: "error", message: "The overview could not be verified as this client's version." };
  }
  return { state: "ready", data: overview };
}

// ---------------------------------------------------------------- words

export const TRIAGE_STATUS: Record<TriageMode["status"], string> = {
  current: "Saved result for this exact entry version, under the current configuration",
  earlier_version: "Saved result for this exact entry version, under an earlier configuration; not regenerated",
  unresolved: "Requested earlier without an accepted result; nothing is retried automatically",
  none: "No saved result for this exact entry version",
};

/** Why a triage section is empty, in words; null when it has something to show. */
export function triageGap(section: TriageSection): string | null {
  switch (section.state) {
    case "results":
      return null;
    case "none":
      return "No headline triage result is saved for this exact entry version. Triage happens only when you select " +
        "entries in the Event Inbox and approve a response there.";
    case "no_entry":
      return "The Inbox entry is no longer held locally, so no triage can be matched to it.";
    case "no_origin":
      return "This saved event has no recorded Inbox origin, so no headline triage is linked to it. Captures made " +
        "before origins were recorded, or typed by hand, keep that gap; nothing is matched by title or date.";
    case "origin_unreadable":
      return "The recorded Inbox origin cannot be read, so no triage is linked.";
    case "origin_not_held":
      return "The Inbox entry version this event started from is no longer held locally, so its triage cannot be read.";
    case "not_offered":
      return "Headline triage is not offered for records imported from a retained snapshot: its prompt names the five " +
        "feeds, and no saved result or fingerprint changes because of an import.";
  }
}

/** The provenance line of one triage result. */
export function triageProvenance(mode: TriageMode): string {
  const p = mode.provenance;
  if (!p) return "";
  const configuration = `${p.config.model}, ${p.config.prompt_version}, ${p.config.schema_version}` +
    (p.current_config ? "" : " (an earlier configuration)");
  const recheck = p.revalidation
    ? ` Accepted on a local re-check under ${p.revalidation.validation_policy} on ${p.revalidation.revalidated_at}; ` +
      `the original response was recorded as ${p.revalidation.original_outcome.replace("_", " ")} under ` +
      `${p.revalidation.original_validation_policy}. Nothing was regenerated or re-sent.`
    : ` Accepted under ${p.validation_policy}.`;
  return `${mode.mode === "paid" ? "Model response" : "Local simulation"} from ${p.triage_id}, received ` +
    `${p.received_at}; ${configuration}.${recheck}`;
}

const ANALYSIS_GAP: Record<string, string> = {
  none: "No analysis is recorded for this saved event. Open it from Saved events in Analyze an event on the Tracker " +
    "to preview its request; nothing is sent without your approval there.",
  incomplete: "An attempt was started but did not finish; it is kept as recorded and is never sent again.",
  awaiting_publication: "The response is recorded but not yet published for review. Analyze an event can publish it " +
    "from the recorded files; nothing is sent or generated again.",
  unreadable: "The recorded analysis could not be read, so nothing is shown in its place.",
};

export function analysisGap(state: string, detail: string | null | undefined): string {
  const base = ANALYSIS_GAP[state] ?? `State: ${state}.`;
  return detail && state !== "none" ? `${base} ${detail}` : base;
}

/** What the market section says when it has no view, or about the view it has. */
export function marketSummary(section: MarketSection): string {
  switch (section.state) {
    case "unsupported":
      return section.event?.outside ?? "This event is outside the first market-context slice.";
    case "unreadable":
      return `The market context cannot be read: ${section.problem ?? "no reason was given"}.`;
    case "needs_date":
      return "No context date is confirmed for this entry yet. Confirm one on its market-context page; nothing is " +
        "requested by opening it.";
    case "stale_confirmation": {
      const stale = section.event?.confirmation_stale;
      return `A context date (${stale?.context_date}) was confirmed for an earlier version of this entry ` +
        `(“${stale?.title}”). It does not carry over: confirm the date for the version held now.`;
    }
    case "no_data":
      return "No local market data covers this window yet. Its market-context page shows what one approved request " +
        "would retrieve; nothing is requested by opening it.";
    case "partial": {
      const plan = section.plan;
      return `Part of the window is held locally${plan ? `: ${plan.held_sessions} of ${plan.needed_sessions} sessions ` +
        `before today` : ""}. Missing, future and conflicting dates are marked below; nothing is filled in.`;
    }
    case "complete":
      return "Every expected session in the window is held locally.";
  }
}

/** What a recorded origin says, or that there is none. */
export function originLine(origin: OriginLink): string {
  if (origin.state === "none") return "No Inbox origin is recorded for this saved event. Nothing is inferred from its " +
    "title, date or link.";
  if (origin.state === "unreadable") return origin.problem ?? "The recorded origin cannot be read.";
  const link = origin.link!;
  const where = origin.entry?.same_version_as_current ? "the version the Inbox holds now"
    : origin.entry?.held ? "an earlier version; the entry has changed since" : "a version no longer held locally";
  const edits = [link.form.headline_matches ? "" : "the headline was edited",
                 link.form.source_url_matches ? "" : "the source address was edited"].filter(Boolean);
  return `Started from Inbox entry version ${link.inbox.version ?? "?"} of ${link.inbox.versions} (${where}), recorded ` +
    `${link.recorded_at}${edits.length ? `; before capture, ${edits.join(" and ")}` : ""}.`;
}

// ---------------------------------------------------------------- processing history

export const HISTORY_STEP: Record<HistoryStep, { title: string; empty: string }> = {
  source: { title: "Source and retained versions",
            empty: "No retrieval of this event is recorded." },
  triage: { title: "Headline triage", empty: "No headline triage request carried this entry." },
  analysis: { title: "Analysis requests and outcomes",
              empty: "No saved event recorded this entry as its origin, so no analysis is linked." },
  review: { title: "Human reviews", empty: "No human review is recorded." },
  use: { title: "Use in a frozen hypothesis",
         empty: "No hypothesis was frozen from an analysis of this event. Research intake is closed, so no event is " +
                "used in research scores." },
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The history in one sentence. "Not processed" is a valid state, not a failure. */
export function historyStatement(history: ProcessingHistory): string {
  const s = history.summary;
  const seen = s.retrievals ? `listed by ${plural(s.retrievals, "recorded retrieval")}` +
    (s.versions > 1 ? ` across ${s.versions} versions` : "") : "with no recorded retrieval";
  if (history.state === "not_processed") {
    return `Not processed: ${seen}; no triage, analysis or review is recorded. That is a valid state.`;
  }
  const done = [s.model_triage ? plural(s.model_triage, "model triage result") : "",
                s.simulated_triage ? `${plural(s.simulated_triage, "simulated triage result")} (no model read it)` : "",
                s.captures ? plural(s.captures, "saved event") : "", s.drafts ? plural(s.drafts, "recorded draft attempt") : "",
                s.reviews ? plural(s.reviews, "review version") : "",
                s.research_requests ? `${plural(s.research_requests, "research request")} prepared` : "",
                s.research_results ? plural(s.research_results, "recorded research result") : "",
                s.research_reviews ? plural(s.research_reviews, "research review version") : "",
                s.frozen ? plural(s.frozen, "frozen hypothesis", "frozen hypotheses") : ""].filter(Boolean);
  const attention = history.state === "needs_attention"
    ? ` Needs attention: ${[s.uncertain ? plural(s.uncertain, "uncertain send") : "",
                            s.failed ? plural(s.failed, "failed or unreadable step") : ""].filter(Boolean).join(" and ")}.`
    : "";
  return `${seen.charAt(0).toUpperCase()}${seen.slice(1)}; ${done.length ? done.join(", ") : "triage prepared or attempted"}.` +
    attention;
}

const usd = (value: number) => (value === 0 ? "$0" : `$${value.toFixed(value < 1 ? 4 : 2)}`);

/** A cost with its kinds kept apart; unknown amounts say so. */
export function costLine(cost: HistoryCost): string {
  const parts = [cost.estimate_usd !== null ? `planning estimate ${usd(cost.estimate_usd)}` : "",
                 cost.usage_usd !== null ? `usage-derived ${usd(cost.usage_usd)}` : "usage-derived: unknown",
                 cost.billing === "not_verified" ? "billing not verified" : ""].filter(Boolean);
  return `${parts.join(" · ")}. ${cost.basis}`;
}

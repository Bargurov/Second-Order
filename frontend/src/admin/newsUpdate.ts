// An update run (news-update-0.1, second_order/news_updates.py): the plan, the recorded runs and one run's report, as
// the News desk reads them, with the words the panel shows. Reading a plan or a report requests, sends and writes
// nothing; every action is its own explicit POST.

export const UPDATE_VERSION = "news-update-0.1";

export const updatePaths = {
  updates: "/api/admin/news/updates",
  run: (runId: string) => `/api/admin/news/updates/${encodeURIComponent(runId)}`,
  step: (runId: string, step: "refresh" | "texts" | "relevance" | "context" | "briefs") =>
    `/api/admin/news/updates/${encodeURIComponent(runId)}/${step}`,
};

export const ARRIVAL_CLASSES = ["published_since", "published_before", "time_unknown"] as const;
export type ArrivalClass = (typeof ARRIVAL_CLASSES)[number];
export const STORY_KINDS = ["new_development", "topic_development", "additional_reporting", "discovered_late",
                            "time_unknown", "revised"] as const;
export type StoryKind = (typeof STORY_KINDS)[number];
export const TONES = ["todo", "attention", "failed", "done"] as const;

export interface UpdateSource {
  source: string; label: string; publisher: string; kind: "official" | "publisher"; last_attempt_at: string | null;
  last_success_at: string | null; terms_url: string; action: "request" | "cooldown" | "needs_contact" | "unreadable";
  reason: string | null;
}
export interface Reference { at: string | null; basis: "run" | "baseline" | "retrieval" | "none"; id: string | null;
  statement: string }
export interface UpdatePlan {
  update_version: string; as_of: string; official: boolean; sources: UpdateSource[];
  requests: { feeds: number; skipped: number };
  limits: { feed_requests_per_source: number; retries: number; cooldown_minutes: number; text_requests: number;
            relevance_batch: number; brief_batch: number };
  reference: Reference;
  paid: { enabled: boolean; detail: string; model: string; statement: string;
          relevance: { max_tokens: number; output_at_max_usd: number };
          briefs: { max_tokens: number; output_at_max_usd: number;
                    stages?: { stage: 1 | 2; name: string; max_tokens: number; output_at_max_usd: number }[] } };
  open_run: string | null; statement: string;
}
export interface UpdateRunRow { run_id: string; label: string; started_at: string; refreshed: boolean;
  reference: string | null }
export interface Arrival {
  entry_id: string; publisher: string; role: string; title: string; link: string; at: string;
  at_basis: "published" | "dated" | "first_seen"; first_seen_at: string; published: string | null; class: ArrivalClass;
}
export interface UpdateStory {
  story_id: string; title: string; kind: StoryKind; kind_label: string; first_at: string;
  first_basis: Arrival["at_basis"]; latest_at: string; arrivals: Arrival[]; revised: Arrival[];
  newly_published: boolean; publishers: string[]; topics: { topic_id: string; title: string }[];
  material: { coverage: string; reports: number }; relevance: { state: string; basis: string | null };
  listed: boolean; hot: boolean; brief_state: string; explanation_state: string; published_version: number | null;
  authorship: string | null; published_in_run: boolean; tone: (typeof TONES)[number]; next: string;
  step: string | null;
}
export interface PaidRequest { stage: "relevance" | "briefs"; batch_id: string; story_id: string; title: string;
  request_id: string; estimated_max_usd: number; attempt: string; detail: string | null;
  /** For a brief request: stage 1 (evidence and figures) or stage 2 (interpretation and brief). */
  request_stage?: 1 | 2 | null;
  /** Why an approval now would skip it (its story merged away or changed since the preview, or an earlier request
   *  contract), or null. */
  skipped: string | null }
export interface PaidBatch { stage: "relevance" | "briefs"; batch_id: string; requests: number;
  estimated_max_usd_total: number; approved: boolean; command: string }
export interface UpdateStep { step: string; at: string; by: string; batch_id?: string; method?: "model" | "assisted";
  stories?: string[]; left?: string[]; requests?: number; built?: { story_id: string; bundle_id: string }[] }
export interface TopicFollowUp { story_id: string; title: string; topic_id: string; topic_title: string;
  with_story: string; with_title: string; later_than_topic: boolean; assistant_may_judge: boolean;
  evidence: { names: string[]; figures: string[]; hours_after: number } }
export interface UpdateReport {
  update_version: string; run_id: string; label: string; as_of: string; started_at: string; started_by: string;
  reference: Reference; baseline_id: string; plan: Pick<UpdatePlan, "sources" | "requests" | "limits" | "paid">;
  refresh: { finished_at: string; requests: number; grouping: { new_stories: number; grouped: number; joined: number };
             sources: { source: string; publisher: string; kind: string; requested: boolean; outcome: string;
                        detail: string | null }[] } | null;
  refresh_state: "done" | "interrupted" | "not_started";
  arrivals: Arrival[]; revised: Arrival[]; ungrouped: number; stories: UpdateStory[]; steps: UpdateStep[];
  follow_ups: { pairs: { stories: [string, string]; titles: Record<string, string> }[]; topics: TopicFollowUp[] };
  counts: {
    before: { stories: number; listed: number; explanations: Record<string, number> };
    after: { stories: number; listed: number; explanations: Record<string, number> };
    run: { arrivals: number; by_class: Record<ArrivalClass, number>; revised: number; stories: number;
           by_kind: Record<StoryKind, number>; relevance: Record<string, number>; listed: number;
           explanations: Record<string, number>; published_in_run: number };
    statement: string;
  };
  paid: { enabled: boolean; batches: PaidBatch[]; requests: PaidRequest[]; not_attempted: number;
          not_attempted_estimate_usd: number; sendable: number; sendable_estimate_usd: number;
          attempted: Record<string, number>; statement: string };
  completed: string[]; attention: string[]; failed: string[];
  next: { step: string; text: string; command: string }[];
  labels: { arrivals: Record<ArrivalClass, string>; kinds: Record<StoryKind, string> };
  statement: string;
}

const ARRIVAL_WORDS: Record<ArrivalClass, [string, string]> = {
  published_since: ["published after the reference time", "published after the reference time"],
  published_before: ["older report discovered late", "older reports discovered late"],
  time_unknown: ["with no stated publication time", "with no stated publication time"],
};

/** The run's arrivals in one line, by what their feeds state ("3 published after the reference time · ..."). */
export function arrivalsLine(report: Pick<UpdateReport, "counts">): string {
  const counts = report.counts.run.by_class;
  const parts = ARRIVAL_CLASSES.filter((key) => counts[key] > 0)
    .map((key) => `${counts[key]} ${ARRIVAL_WORDS[key][counts[key] === 1 ? 0 : 1]}`);
  return parts.length ? parts.join(" · ") : "No report arrived.";
}

/** The paid plan in one line: what is saved and not sent, and that its total is a planning estimate. */
export function paidLine(paid: UpdateReport["paid"]): string {
  if (paid.requests.length === 0) return "No paid request is saved for this run.";
  const sent = Object.values(paid.attempted).reduce((sum, value) => sum + value, 0);
  const skipped = paid.not_attempted - paid.sendable;
  const reasons = [...new Set(paid.requests.map((row) => row.skipped).filter((reason) => reason))].join("; ");
  return `${paid.not_attempted} saved request${paid.not_attempted === 1 ? "" : "s"} not sent: an approval now ` +
    `would send ${paid.sendable} (planning estimate $${paid.sendable_estimate_usd.toFixed(4)}, not a billing ceiling)` +
    (skipped ? `, skipping ${skipped} (${reasons})` : "") +
    (sent ? `; ${sent} attempted: ${Object.entries(paid.attempted).map(([state, value]) => `${value} ${state}`)
      .join(", ")}` : "") + ".";
}

/** Whether a reply is a report this panel can show (its version and lists), else why not. */
export function reportProblem(value: unknown): string | null {
  if (typeof value !== "object" || value === null) return "The run's report is not readable.";
  const report = value as Partial<UpdateReport>;
  if (report.update_version !== UPDATE_VERSION) return "The run's report has another version.";
  if (!Array.isArray(report.stories) || !Array.isArray(report.arrivals) || !Array.isArray(report.completed) ||
      !Array.isArray(report.attention) || !Array.isArray(report.failed) || !Array.isArray(report.next)) {
    return "The run's report is not readable.";
  }
  if (!report.stories.every((row) => (STORY_KINDS as readonly string[]).includes(row.kind) &&
      (TONES as readonly string[]).includes(row.tone))) return "A story of the run is not readable.";
  if (!report.arrivals.every((row) => (ARRIVAL_CLASSES as readonly string[]).includes(row.class))) {
    return "An arrival of the run is not readable.";
  }
  return null;
}

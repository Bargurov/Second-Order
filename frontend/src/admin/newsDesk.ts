// The News desk's payloads and the brief editor's text format (admin-api-0.4, docs/news-stories-contract.md section 6).
// Admin-only: membership history, actors, idempotency, unpublished versions, the ranking's points and the paid draft's
// planning estimate live here and never in src/contracts/stories.ts. Every write is one explicit POST through
// adminPost with its own idempotency key; nothing here retries.

export interface DeskReport {
  entry_id: string; version_sha256: string; source: string; publisher: string; role_label: string; title: string;
  excerpt: string | null; link: string; first_seen_at: string; listing: string; stale: boolean; at: string;
  at_basis: "published" | "dated" | "first_seen"; material: "permitted" | "none"; display: string; synthetic: boolean;
  text?: { state: string; characters?: number; retrieved_at?: string; partial_reason?: string | null;
           detail?: string | null };
}
export interface TextPlanRow { entry_id: string; publisher: string; title: string; link: string;
  action: "request" | "reuse" | "reread" | "not_supported" }
export interface BriefContent {
  headline: string; summary: string; facts: { text: string; reports: string[] }[]; implications: { text: string }[];
  themes: { kind: "sector" | "company" | "theme"; name: string; basis: string }[]; uncertainties: string[];
  missing: string[];
}
export interface Material {
  material_sha256: string; statement: string; coverage: string;
  reports: { entry_id: string; publisher: string; title: string; excerpt: string | null }[];
  not_used: { entry_id: string; publisher: string; title: string; reason: string }[];
}
export interface BriefVersion {
  version: number; based_on: number | null; method: string; content: BriefContent; material_sha256: string;
  material_statement: string; preparation: Record<string, unknown>; problems: string[];
  guard: { findings: { where: string; rule: string; matched: string; detail: string }[] }; actor: string; at: string;
  authorship: "editor" | "ai_model" | "ai_assistant" | "synthetic";
  reviews: { reviewer: string; at: string; note: string }[]; covers_current_material: boolean;
}
export interface Assessment { material_sha256: string; verdict: "insufficient" | "sufficient"; reason: string;
  method: string; actor: string; at: string }
export interface Evidence { report: string; quote: string }
export interface Annotation {
  report_kind: string; event_type: string | null; change: string; change_evidence: Evidence[];
  affected: { name: string; kind: string; evidence: Evidence[] }[];
  dimensions: { dimension: string; how: string; evidence: Evidence[] }[];
  scope: { reach: string; magnitudes: { text: string; evidence: Evidence }[] }; ambiguities: string[];
  missing: string[]; verdict: string; explanation: string;
}
export interface AnnotationRow {
  event_id: number; method: string; outcome: "annotated" | "failed"; material_sha256: string;
  annotation: Annotation | null;
  evidence: { found: number; not_found: number; supported_dimensions: string[];
              quotes: { where: string; report: string; found: boolean; field: string | null; problem: string | null }[];
              detail?: string };
  versions: Record<string, string>; preparation: Record<string, unknown>; actor: string; at: string;
  decision: { state: string; reasons: string[] } | null;
}
export interface Importance { points: number; level: string; text: string }
export interface StoryRelevanceState {
  state: string; basis: string | null; explanation: string; current: boolean | null; importance: Importance | null;
  review: { verdict: string; reason: string; actor: string; at: string } | null;
}
export interface DeskStory {
  story_id: string; title: string; first_at: string; latest_at: string; reports: number; publishers: string[];
  relevance: StoryRelevanceState; relevance_history: AnnotationRow[];
  relevance_reviews: { verdict: string; reason: string; actor: string; at: string }[];
  older: boolean; stale: boolean; synthetic: boolean;
  brief: { state: string; summary: string | null; current: boolean | null };
  insufficient: string | null; assessments: Assessment[];
  rank: { score: number; hot: boolean; signals: { signal: string; points: number; text: string }[] };
  reports_detail: DeskReport[]; coverage_detail: { reporting_origins: number; confirmed_news: number; confirmed_official: number;
    possible_news: number; possible_official: number; repeats: number; company_statements: number };
  history: { action: string; entry_id: string; basis: Record<string, unknown>; actor: string; at: string;
             reason: string }[];
  merged_from: string[]; material: Material; versions: BriefVersion[];
  publications: { version: number | null; actor: string; at: string; reason: string }[];
  published_version: number | null;
  priority: { level: string; until: string | null; reason: string } | null;
  topics: { topic_id: string; title: string }[];
}
export interface DeskPublisher {
  source: string; publisher: string; role_label: string; status: string; display: string; material: string;
  material_basis: string; terms_url: string; checked: string; credentials: string | null; agreement: string | null;
  note: string; live_verified: string | null; synthetic: boolean; feed_url: string | null;
}
export interface DeskSource { source: string; publisher: string; state: string; last_success_at: string | null;
  stale: boolean; reports: number }
export interface DeskTopic {
  topic_id: string; title: string; summary: string; at: string; reason: string;
  timeline: { story_id: string; label: string; title: string; first_at: string }[];
  priority: { level: string; until: string | null } | null;
}
export interface Desk {
  desk_version: string; as_of: string; newsroom: { exists: boolean; schema: string };
  registry: { registry_version: string; publishers: DeskPublisher[] }; sources: DeskSource[];
  ungrouped: DeskReport[]; stories: DeskStory[];
  suggestions: MatchCandidate[];
  match_decisions: { story_a: string; story_b: string; decision: string; method: string; topic_id: string | null;
                     reason: string; actor: string; at: string }[];
  topics: DeskTopic[]; rank: { statement: string }; match: { statement: string };
  drafting: { enabled: boolean; detail: string; model: string; max_tokens_by_stage: Record<string, number> };
}
/** A pair of stories that may report one development (story-match-0.2), with its evidence. */
export interface MatchCandidate {
  stories: [string, string]; titles: Record<string, string>; publishers: Record<string, string[]>;
  evidence: { names: string[]; figures: string[]; word_overlap: number; hours_apart: number };
  cross_publisher: boolean; assistant_may_judge: boolean; score: number;
}
type Attempt = { state: string; detail: string | null; version: number | null; request_id?: string | null;
                 provider_error?: ProviderError | null };
type Estimate = { estimated_real_run_if_output_reaches_max_usd: number; caveat: string };
/** One stage of a two-stage model draft (brief-drafting-0.2): its exact request once prepared, else its plan. */
export interface DraftingStage {
  stage: 1 | 2; name: string; does: string; stage_version: string; draft_id: string | null;
  request_sha256: string | null; max_tokens: number; estimate: Estimate | null;
  /** exact: this request's own bytes; planned: from the largest first stage the limits allow; not_needed. */
  estimate_kind: "exact" | "planned" | "not_needed"; attempt: Attempt | null; usage_cost: { usd: number } | null;
}
/** A story's two-stage model draft: the request an approval now would send (or the last one attempted), and both
 *  stages with what each does, its estimate and its state. */
export interface DraftingPreview {
  draft_id: string; story_id: string; request_sha256: string; model: string; max_tokens: number;
  stage: 1 | 2; next_stage: 1 | 2 | null; state: "awaiting_stage_1" | "awaiting_stage_2" | "complete" | "stopped";
  detail: string; material_statement: string; estimate: Estimate; attempt: Attempt; stages: DraftingStage[];
  combined: { planning_estimate_usd: number; remaining_planning_estimate_usd: number; usage_cost_usd: number | null;
              statement: string };
  sending: { enabled: boolean; detail: string };
}

/** One stage as a line for the operator: what it is, its estimate (exact or planned) and output limit, its attempt
 *  and the usage its reply reported. */
export function stageLine(stage: DraftingStage): string {
  const estimate = stage.estimate ? `${stage.estimate_kind === "planned" ? "planned estimate" : "planning estimate"} ` +
    `$${stage.estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4)}` : "not needed";
  const attempt = stage.attempt ? ` · ${stage.attempt.state}` : stage.estimate_kind === "planned" ?
    " · prepared after stage 1 passes, approved on its own" : "";
  const used = stage.usage_cost ? ` · reported usage $${stage.usage_cost.usd.toFixed(4)}` : "";
  return `Stage ${stage.stage}, ${stage.name.toLowerCase()}: ${estimate}, at most ` +
    `${stage.max_tokens.toLocaleString("en-US")} output tokens${attempt}${used}.`;
}

/** What was kept of a provider's non-success reply (provider-error-0.1): bounded and checked for the credential. */
export interface ProviderError {
  http_status: number; error_type: string | null; message: string | null; message_truncated: boolean;
  request_id: string | null;
}

/** The provider's request ID and error message kept with a draft attempt, as one line, or null when none was kept
 *  (a success, a reply without them, or an attempt recorded before they were kept). */
export function providerNote(attempt: Attempt): string | null {
  const id = attempt.request_id ? `Provider request ID ${attempt.request_id}.` : "";
  const message = attempt.provider_error?.message ? `Provider message: ${attempt.provider_error.message}` : "";
  return id || message ? [id, message].filter(Boolean).join(" ") : null;
}

export interface CoverageRow {
  story_id: string; title: string; latest_at: string; score: number; hot: boolean; state: string;
  material: { coverage: string; reports: number; texts: number; texts_open: number };
  published_version: number | null; insufficient: string | null; publishers: string[]; relevance: string;
  relevance_basis: string | null; explanation?: string;
}
export interface Coverage {
  coverage_version: string; as_of: string;
  important: { stories: number; eligible: number; counts: Record<string, number>; ready_share_of_eligible: number | null;
               rows: CoverageRow[] };
  all: { stories: number; counts: Record<string, number> };
  current_relevance: { stories: number; counts: Record<string, number>; statement: string };
  explanations?: { important: Record<string, number>; listed: { stories: number; counts: Record<string, number> };
                   statement: string };
  readiness: { newsroom: { schema: string | null; needs_upgrade: boolean };
               paid_drafting: { enabled: boolean; detail: string }; texts: { kept: boolean };
               credit_policy: { published: boolean; detail: string } | null };
  statement: string;
}
export interface Batch {
  batch_id: string; method: "model" | "assisted"; created_at: string; estimated_max_usd_total: number | null;
  texts_open: number; statement: string;
  items: { story_id: string; title: string; action: string; state: string; material_sha256: string;
           material: { coverage: string; statement: string; reports: number; texts: number; texts_open: number };
           draft?: { draft_id: string; stage?: 1 | 2; request_sha256: string; estimated_max_usd: number } }[];
  stages?: (1 | 2)[] | null; followup_estimated_max_usd_total?: number | null;
}
export interface BatchStatus {
  batch_id: string; approval: { approved_by: string; approved_at: string } | null;
  items: { story_id: string; title: string; state?: string; material_changed?: boolean; stage?: 1 | 2 | null;
           attempt?: { state: string; detail: string | null } | null; version?: number | null;
           problems?: string[] | null; published?: boolean; insufficient?: string | null }[];
}

export interface RelevanceRow {
  story_id: string; title: string; latest_at: string; age_hours: number; publishers: string[]; state: string;
  basis: string | null; explanation: string; current: boolean | null; importance: Importance | null; hot: boolean;
  decision: { state: string; reasons: string[] } | null; next: string | null;
  material: { coverage: string; reports: number; texts: number };
}
export interface RelevanceQueue {
  window_hours: number; counts: Record<string, number>; all_counts: Record<string, number>; rows: RelevanceRow[];
  candidates: number; versions: Record<string, string>; decision_version: string; importance_version: string;
  sending: { enabled: boolean; detail: string; model: string; max_tokens: number }; statement: string;
}
export interface RelevanceBatch {
  batch_id: string; method: "model" | "assisted"; model: string | null; created_at: string;
  estimated_max_usd_total: number | null; statement: string;
  items: { story_id: string; title: string; reason: string; state: string; attempt: number; material_sha256: string;
           material: { coverage: string; statement: string; reports: number; texts: number };
           request?: { request_id: string; request_sha256: string; estimated_max_usd: number } }[];
  left: { story_id: string; title: string; state: string; why: string }[];
}
export interface RelevanceBatchStatus {
  batch_id: string; approval: { approved_by: string; approved_at: string } | null;
  items: { story_id: string; title: string; state?: string; material_changed?: boolean;
           attempt?: { state: string; detail: string | null } | null; outcome?: string | null }[];
}

export const newsPaths = {
  relevance: "/api/admin/news/relevance",
  relevanceBatches: "/api/admin/news/relevance/batches",
  relevanceBatch: (batchId: string) => `/api/admin/news/relevance/batches/${encodeURIComponent(batchId)}`,
  relevanceBatchAction: (batchId: string, action: "approval" | "packet") =>
    `/api/admin/news/relevance/batches/${encodeURIComponent(batchId)}/${action}`,
  desk: "/api/admin/news",
  coverage: "/api/admin/news/coverage",
  batches: "/api/admin/news/batches",
  batch: (batchId: string) => `/api/admin/news/batches/${encodeURIComponent(batchId)}`,
  batchAction: (batchId: string, action: "approval" | "publication" | "packet") =>
    `/api/admin/news/batches/${encodeURIComponent(batchId)}/${action}`,
  refresh: "/api/admin/news/feeds/refresh",
  matches: "/api/admin/news/matches",
  group: "/api/admin/news/group",
  story: (storyId: string, action: "merge" | "detach" | "title" | "briefs" | "publication" | "drafting" | "draft" |
                                  "reviews" | "assessment" | "texts" | "relevance") =>
    `/api/admin/news/stories/${encodeURIComponent(storyId)}/${action}`,
  topics: "/api/admin/news/topics",
  links: (topicId: string) => `/api/admin/news/topics/${encodeURIComponent(topicId)}/links`,
  priorities: "/api/admin/news/priorities",
  approval: (draftId: string) => `/api/admin/news/drafting/${encodeURIComponent(draftId)}/approval`,
};

// ---------------------------------------------------------------- the brief editor's text format
// One item per line. A fact ends with the numbers of the material reports it rests on in brackets ("... [1, 2]"); a
// theme is "kind | name | basis". Nothing is guessed: a line that does not parse is reported, never dropped.

export interface EditorText {
  headline: string; summary: string; facts: string; implications: string; themes: string; uncertainties: string;
  missing: string;
}

const lines = (value: string) => value.split("\n").map((line) => line.trim()).filter((line) => line !== "");

export function toEditor(content: BriefContent, material: Material): EditorText {
  const number = (entry: string) => material.reports.findIndex((row) => row.entry_id === entry) + 1;
  return {
    headline: content.headline, summary: content.summary,
    facts: content.facts.map((fact) => `${fact.text} [${fact.reports.map(number).join(", ")}]`).join("\n"),
    implications: content.implications.map((row) => row.text).join("\n"),
    themes: content.themes.map((row) => `${row.kind} | ${row.name} | ${row.basis}`).join("\n"),
    uncertainties: content.uncertainties.join("\n"), missing: content.missing.join("\n"),
  };
}

export function fromEditor(text: EditorText, material: Material): { content: BriefContent | null; problems: string[] } {
  const problems: string[] = [];
  const facts = lines(text.facts).map((line, index) => {
    const found = /^(.*\S)\s*\[([\d,\s]+)\]$/.exec(line);
    const numbers = found ? found[2].split(",").map((part) => Number(part.trim())) : [];
    const reports = numbers.map((value) => material.reports[value - 1]?.entry_id);
    if (!found || reports.length === 0 || reports.some((entry) => entry === undefined)) {
      problems.push(`Fact ${index + 1} must end with the numbers of the material reports it rests on, as [1] or [1, 2].`);
      return null;
    }
    return { text: found[1], reports: reports as string[] };
  });
  const themes = lines(text.themes).map((line, index) => {
    const parts = line.split("|").map((part) => part.trim());
    if (parts.length !== 3 || !["sector", "company", "theme"].includes(parts[0]) || !parts[1] || !parts[2]) {
      problems.push(`Theme ${index + 1} must be "sector | name | basis" (or company, or theme).`);
      return null;
    }
    return { kind: parts[0] as "sector" | "company" | "theme", name: parts[1], basis: parts[2] };
  });
  if (problems.length > 0) return { content: null, problems };
  return {
    problems,
    content: {
      headline: text.headline.trim(), summary: text.summary.trim(), facts: facts as BriefContent["facts"],
      implications: lines(text.implications).map((line) => ({ text: line })),
      themes: themes as BriefContent["themes"], uncertainties: lines(text.uncertainties), missing: lines(text.missing),
    },
  };
}

export const STATUS_LABEL: Record<string, string> = {
  connected: "Connected", needs_agreement: "Needs an agreement", needs_credentials: "Needs credentials",
  not_connected: "Not connected", fixture_only: "Fixture only (SYNTHETIC)",
};

/** Who prepared a version, in the desk's words; an assisted version names the tool (and model) the operator declared. */
export function authorshipText(version: BriefVersion): string {
  const assistant = (version.preparation as { assistant?: { tool: string; model: string | null } }).assistant;
  if (version.authorship === "ai_assistant" && assistant) {
    return `AI-assisted (${assistant.tool}${assistant.model ? `, ${assistant.model}` : ""}; declared)`;
  }
  return { editor: "written by an editor", ai_model: "drafted by the AI model in this application",
           ai_assistant: "AI-assisted", synthetic: "SYNTHETIC" }[version.authorship];
}

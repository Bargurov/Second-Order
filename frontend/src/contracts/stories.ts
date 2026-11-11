// The stories, topics and Go deeper routes of user-api-0.5 (docs/news-stories-contract.md). Owned by the logic
// conversation, like src/contracts/user.ts and src/contracts/news.ts; the Client imports it and never edits it.
//
// Every reader is fail-closed: a payload missing a required field, carrying an unknown state or contradicting itself
// (a published brief without its content, a story whose deeper analysis is unavailable without a reason, a fact citing a
// report its brief's material does not hold) is refused as unreadable rather than shown. Reads only read on the server:
// no publisher is contacted, no model is called and nothing is counted or charged by opening a story. The one write, Go
// deeper, is an explicit action that saves the user's own source and prepares its analysis; it quotes, sends and charges
// nothing, and the request helpers never retry.
import { INTERESTS, publishedProblem, type Interest, type Published } from "./news.ts";
import { economicsProblem, explanationProblem, type Economics, type Explanation } from "./economics.ts";
import {
  EFFORTS, SHA, SOURCE_ID, USER_HEADER, count, listProblem, oneOf, record, request, text, texts, time, wrapped,
  type AccountBinding, type Analysis, type Effort, type Fetcher, type Read, type Reply,
} from "./user.ts";

export const STORIES_VIEW_VERSION = "news-stories-view-0.5";
export const STORY_VIEW_VERSION = "news-story-view-0.6";
export const TOPICS_VIEW_VERSION = "news-topics-view-0.1";
export const RANK_VERSION = "news-rank-0.4";
export const BRIEF_VERSION = "story-brief-0.4";
/** Who says what (story-brief-0.4, brief-claims-0.1): whose a claim is and how it was put. */
export const CLAIMS_VERSION = "brief-claims-0.1";
export const HOLDERS = ["issuer", "speaker", "interviewer", "operative_text", "respondents", "other_party"] as const;
export const MODALITIES = ["asserted", "conditional", "prospective", "view", "question"] as const;
export const DEEPER_VERSION = "story-deeper-0.2";
export const COVERAGE_VERSION = "story-coverage-0.3";
export const VIEWS = ["hot", "coverage", "latest", "interests"] as const;
export const TIME_BASES = ["published", "dated", "first_seen"] as const;
export const BRIEF_STATES = ["published", "withdrawn", "not_permitted", "insufficient", "none"] as const;
export const BRIEF_METHODS = ["editorial", "extract", "model", "assisted", "synthetic"] as const;
/** Who prepared a brief: a person (editorial, extract), an AI model in this application, an AI assistant outside it. */
export const AUTHORSHIPS = ["editor", "ai_model", "ai_assistant", "synthetic"] as const;
/** Whether a person read the published version: only a recorded review says so; publishing is not reviewing. */
export const REVIEW_STATES = ["written_by_editor", "read_by_editor", "not_reviewed"] as const;
export const AUTHORSHIP_OF: Record<(typeof BRIEF_METHODS)[number], (typeof AUTHORSHIPS)[number]> = {
  editorial: "editor", extract: "editor", model: "ai_model", assisted: "ai_assistant", synthetic: "synthetic",
};
export const ROLES = ["official", "news", "company"] as const;
export const DISPLAYS = ["headline_excerpt", "headline"] as const;
export const MATERIAL = ["permitted", "none"] as const;
export const USES = ["material", "permitted", "listed"] as const;
export const THEME_KINDS = ["sector", "company", "theme"] as const;
export const COVERAGES = ["none", "headlines", "headlines_and_excerpts", "partial_text", "full_text"] as const;
/** What this server holds of a report's publication text (news_texts): the full text, part of it, a failed reading, not
 * yet retrieved, or not read for this publisher at all. */
export const TEXT_STATES = ["full_text", "partial_text", "failed", "not_retrieved", "not_supported"] as const;
export const SIGNALS = ["freshness", "new_development", "coverage", "breaking", "priority", "topic", "importance",
  "statements_only", "relevance"] as const;
/** Whether a reporting origin's independence from the story's other origins is established (story-coverage-0.3). */
export const INDEPENDENCE = ["established", "unverified"] as const;
/** A story's economic relevance (news-relevance-0.1): established (relevant), left out (outside_scope), or awaiting an
 * assessment or an editor (insufficient, needs_review, unavailable, restricted by its publisher's terms, pending). */
export const RELEVANCE_STATES = ["relevant", "outside_scope", "insufficient", "needs_review", "unavailable",
  "restricted", "pending"] as const;
export const AWAITING_STATES = ["pending", "restricted", "needs_review", "unavailable", "insufficient"] as const;
/** Who decided it: an editor, the AI model in this application, an AI assistant outside it, or a SYNTHETIC record. */
export const RELEVANCE_BASES = ["editor", "model", "assisted", "synthetic"] as const;
export const DIMENSIONS = ["demand", "revenue", "costs", "prices", "production", "employment", "financing",
  "competition", "regulation", "trade", "capacity"] as const;
export const SOURCE_STATES = ["never_refreshed", "ok", "failed", "not_requested", "unreadable"] as const;
export const REGISTRY_STATUSES = ["connected", "needs_agreement", "needs_credentials", "not_connected",
  "fixture_only"] as const;

export type View = (typeof VIEWS)[number];
export type RelevanceState = (typeof RELEVANCE_STATES)[number];
export type Dimension = (typeof DIMENSIONS)[number];
export type BriefState = (typeof BRIEF_STATES)[number];
export type Role = (typeof ROLES)[number];

// ---------------------------------------------------------------- payload types

export interface Signal { signal: (typeof SIGNALS)[number]; text: string }
/** Publishers apart from reporting origins: an origin is one publisher, or several carrying one text (a wire copy or
 * a republished release); origins are a newsroom's own reporting, official statements or company statements. The news
 * and official origins are the reporting origins, each confirmed (its independence established) or possible (not
 * established), by kind (story-coverage-0.3). */
export interface CoverageCounts {
  publishers: number; origins: number; news_origins: number; official_origins: number; company_origins: number;
  reporting_origins: number; confirmed_news: number; confirmed_official: number; possible_news: number;
  possible_official: number; uncertain: number; repeats: number; company_statements: number; official_releases: number;
}
export interface StoryCard {
  story_id: string; title: string; first_at: string; first_basis: (typeof TIME_BASES)[number]; latest_at: string;
  latest_basis: (typeof TIME_BASES)[number]; reports: number; publishers: string[]; coverage: CoverageCounts;
  interests: Interest[]; topics: { topic_id: string; title: string }[];
  brief: { state: BriefState; summary: string | null; current: boolean | null;
           authorship: (typeof AUTHORSHIPS)[number] | null; review: (typeof REVIEW_STATES)[number] | null;
           explained: boolean };
  excerpt: { publisher: string; text: string } | null;
  relevance: { state: RelevanceState; statement: string };
  older: boolean; stale: boolean; synthetic: boolean; signals: Signal[];
}
export interface Relevance {
  state: RelevanceState; statement: string; basis: (typeof RELEVANCE_BASES)[number] | null; basis_label: string | null;
  explanation: string | null; change: string | null; dimensions: { dimension: Dimension; how: string }[];
  missing: string[]; current: boolean | null;
}
export interface TopicCard {
  topic_id: string; title: string; summary: string; developments: number; latest_at: string | null;
  latest_title: string | null; synthetic: boolean;
}
export interface SourceRow {
  source: string; publisher: string; name: string; label: string; role: Role; role_label: string;
  state: (typeof SOURCE_STATES)[number]; last_success_at: string | null; stale: boolean; reports: number;
  display: (typeof DISPLAYS)[number]; material: (typeof MATERIAL)[number]; attribution: string; terms_url: string;
  synthetic: boolean;
}
export interface StoriesView {
  view_version: typeof STORIES_VIEW_VERSION; view: View; as_of: string;
  rank: { rank_version: typeof RANK_VERSION; hot_hours: number; statement: string }; interests: Interest[];
  stories: StoryCard[]; awaiting: StoryCard[];
  left_out: { outside_scope: number; older_unassessed: number; statement: string };
  topics: TopicCard[]; sources: SourceRow[]; notes: string[]; statement: string;
}
export interface Coverage extends CoverageCounts {
  coverage_version: typeof COVERAGE_VERSION; reports: number; publishers: number;
  units: { publishers: string[]; entries: string[]; counted_together_because: string[]; role: Role;
           independence: (typeof INDEPENDENCE)[number]; uncertain_because: string[] }[];
  possible_shared_origins: { entries: string[]; reason: string }[];
}
export interface BriefContent {
  headline: string; summary: string; facts: { text: string; reports: string[]; claims?: string[] }[];
  implications: { text: string }[]; themes: { kind: (typeof THEME_KINDS)[number]; name: string; basis: string }[];
  uncertainties: string[]; missing: string[];
  /** Who says what (story-brief-0.4); absent for a brief that records none. Every fact then names its claims. */
  claims?: BriefClaim[];
}
export interface BriefClaim {
  id: string; holder: (typeof HOLDERS)[number]; holder_name: string; modality: (typeof MODALITIES)[number];
  quote: string; condition: string | null; source: string;
}
/** "Who says what": each recorded claim with its labels, its source report and the facts that cite it (1-based). */
export interface ClaimsView {
  claims_version: typeof CLAIMS_VERSION; statement: string;
  claims: (BriefClaim & { holder_label: string; modality_label: string; reports: string[]; link: string | null;
                          facts: number[] })[];
}
export interface Brief {
  brief_version: typeof BRIEF_VERSION; version: number; content: BriefContent;
  method: (typeof BRIEF_METHODS)[number]; method_label: string; authorship: (typeof AUTHORSHIPS)[number];
  review: { state: (typeof REVIEW_STATES)[number]; statement: string }; current: boolean; update_note: string | null;
  prepared_at: string; published_at: string;
  material: { coverage: (typeof COVERAGES)[number]; statement: string;
              reports: { entry_id: string; publisher: string; title: string }[];
              not_used: { publisher: string; title: string; reason: string }[] };
  reports_since: number; synthetic: boolean; economics: Economics | null; statement: string;
  /** Who says what, for a version that records claims (story-brief-0.4); absent otherwise. */
  claims?: ClaimsView;
  /** What the explanation read beyond the story's own material (passages are not the whole publication). */
  context_statement?: string | null;
  /** The versions readers were shown before this one, newest first, and what this one changed (story view 0.6). */
  revisions: BriefRevisions;
}
export interface BriefRevisions {
  /** method and authorship as corrected; recorded_as: the method first recorded, when a correction changed it;
   * corrects: the version whose authorship this one corrects. */
  earlier: { version: number; published_at: string; prepared_at: string; method: (typeof BRIEF_METHODS)[number];
             authorship: (typeof AUTHORSHIPS)[number]; recorded_as: (typeof BRIEF_METHODS)[number] | null;
             corrects: number | null; headline: string; summary: string; reports: number; explained: boolean }[];
  changes: string[]; updated_at: string | null;
}
export interface StorySource {
  entry_id: string; publisher: string; role: Role; role_label: string; kind: string; title: string;
  title_shortened: boolean; excerpt: string | null; excerpt_shortened: boolean; link: string; published: Published;
  first_seen_at: string; listing: "current" | "retained"; stale: boolean; attribution: string; synthetic: boolean;
  unit: number; counted_together_because: string[]; use: (typeof USES)[number]; text: TextState;
}
export interface TextState {
  state: (typeof TEXT_STATES)[number]; characters: number | null; retrieved_at: string | null;
  partial_reason: string | null; detail: string | null;
}
export interface MaterialText {
  state: "full_text" | "partial_text"; text_sha256: string; characters: number; retrieved_at: string; url: string;
  extractor: string; partial_reason: string | null;
}
export interface Deeper { available: boolean; material_reports: number; reason: string | null }
export interface StoryPage {
  view_version: typeof STORY_VIEW_VERSION; story_id: string; requested_id: string; merged: boolean; title: string;
  title_basis: "editors" | "first_report"; first_at: string; first_basis: (typeof TIME_BASES)[number];
  latest_at: string; latest_basis: (typeof TIME_BASES)[number]; coverage: Coverage; interests: Interest[];
  signals: Signal[]; older: boolean; stale: boolean; synthetic: boolean; brief_state: BriefState;
  brief_note: string | null; brief: Brief | null; explanation: Explanation; relevance: Relevance;
  sources: StorySource[]; topics: TopicCard[];
  related: { story_id: string; title: string; first_at: string; first_basis: (typeof TIME_BASES)[number];
             label: string | null; topic_id: string }[];
  deeper: Deeper; statement: string;
}
export interface TopicsView { view_version: typeof TOPICS_VIEW_VERSION; as_of: string; topics: TopicCard[];
  notes: string[]; statement: string }
export interface TopicPage extends TopicCard {
  view_version: typeof TOPICS_VIEW_VERSION; timeline: (StoryCard & { label: string | null })[]; statement: string;
}
export interface MaterialReport {
  entry_id: string; version_sha256: string; publisher: string; role: Role; title: string; excerpt: string | null;
  link: string; published: string | null; published_utc: string | null; attribution: string; synthetic: boolean;
  text?: MaterialText;
}
export interface DeeperPreview extends Deeper {
  deeper_version: typeof DEEPER_VERSION; story_id: string; title: string;
  material: { coverage: (typeof COVERAGES)[number]; statement: string; reports: MaterialReport[];
              not_used: { entry_id: string; publisher: string; title: string; link: string; reason: string }[] };
  material_sha256: string;
  source: { headline: string; source_url: string; published_at: string; characters: number; text: string } | null;
  existing: { source_id: string; analyses: { analysis_id: string; effort: Effort }[] } | null; statement: string;
}
export interface DeeperDone {
  deeper_version: typeof DEEPER_VERSION; story_id: string;
  source: { source_id: string; headline: string; source_url: string; published_at: string; captured_at: string;
            characters: number };
  analysis: Analysis; created_source: boolean; created_analysis: boolean;
}

// ---------------------------------------------------------------- readers

const STORY_ID = /^story-[0-9a-f]{16}$/;
const TOPIC_ID = /^topic-[0-9a-f]{16}$/;
const ENTRY_ID = /^[a-z]+(?:-[a-z]+)*:[0-9a-f]{20}$/;
const SOURCE_KEY = /^[a-z]+(?:-[a-z]+)*$/;
const flag = (value: unknown): value is boolean => typeof value === "boolean";
const textOrNull = (value: unknown) => value === null || text(value);
const timeOrNull = (value: unknown) => value === null || time(value);
const https = (value: unknown): value is string => {
  if (typeof value !== "string") return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
};
const storyId = (value: unknown) => typeof value === "string" && STORY_ID.test(value);
const topicId = (value: unknown) => typeof value === "string" && TOPIC_ID.test(value);
const entryId = (value: unknown) => typeof value === "string" && ENTRY_ID.test(value);
const interestList = (value: unknown) => Array.isArray(value) && value.every((item) => oneOf(INTERESTS, item));

function signalsProblem(value: unknown): string | null {
  return Array.isArray(value) && value.every((row) => record(row) && oneOf(SIGNALS, row.signal) && text(row.text))
    ? null : "A story's ranking signals are not readable.";
}

function countsProblem(value: unknown): string | null {
  if (!record(value) || !["publishers", "origins", "news_origins", "official_origins", "company_origins",
    "reporting_origins", "confirmed_news", "confirmed_official", "possible_news", "possible_official", "uncertain",
    "repeats", "company_statements", "official_releases"].every((key) => count(value[key]))) {
    return "A story's coverage is not readable.";
  }
  const n = (key: string) => value[key] as number;
  const sum = n("news_origins") + n("official_origins") + n("company_origins");
  if (sum !== value.origins || n("reporting_origins") !== n("news_origins") + n("official_origins") ||
      n("confirmed_news") + n("possible_news") !== n("news_origins") ||
      n("confirmed_official") + n("possible_official") !== n("official_origins") ||
      n("possible_news") + n("possible_official") > n("uncertain")
      || (value.uncertain as number) > (value.origins as number) || (value.publishers as number) < 1 ||
      (value.origins as number) < 1 || (value.origins as number) > (value.publishers as number)) {
    return "A story's coverage counts disagree.";
  }
  return null;
}

function timesProblem(story: Record<string, unknown>): string | null {
  if (!time(story.first_at) || !time(story.latest_at) || !oneOf(TIME_BASES, story.first_basis) ||
      !oneOf(TIME_BASES, story.latest_basis)) return "A story's times are not readable.";
  return Date.parse(story.first_at as string) <= Date.parse(story.latest_at as string) ? null
    : "A story's first report comes after its latest.";
}

function cardProblem(card: unknown): string | null {
  if (!record(card) || !storyId(card.story_id) || !text(card.title) || !count(card.reports) || card.reports < 1 ||
      !texts(card.publishers) || card.publishers.length === 0 || !interestList(card.interests) ||
      !Array.isArray(card.topics) || !card.topics.every((row) => record(row) && topicId(row.topic_id) &&
        text(row.title)) || !flag(card.older) || !flag(card.stale) || !flag(card.synthetic)) {
    return "A story is not readable.";
  }
  const brief = card.brief, excerpt = card.excerpt;
  if (!record(brief) || !oneOf(BRIEF_STATES, brief.state) || !textOrNull(brief.summary) ||
      (brief.state === "published") !== (brief.summary !== null) ||
      (brief.state === "published" ? !flag(brief.current) : brief.current !== null) || !flag(brief.explained) ||
      !(brief.authorship === null || oneOf(AUTHORSHIPS, brief.authorship)) ||
      !(brief.review === null || oneOf(REVIEW_STATES, brief.review))) {
    return "A story's brief state is not readable.";
  }
  if ((brief.state === "published") !== (brief.authorship !== null && brief.review !== null) ||
      (brief.state !== "published" && brief.explained) ||
      (brief.authorship !== null && (brief.authorship === "editor") !== (brief.review === "written_by_editor"))) {
    return "A story's brief label disagrees with its record.";
  }
  if (excerpt !== null && (!record(excerpt) || !text(excerpt.publisher) || !text(excerpt.text))) {
    return "A story's excerpt is not readable.";
  }
  if (brief.state === "published" && excerpt !== null) return "A story with a brief shows a feed excerpt instead.";
  if (!record(card.relevance) || !oneOf(RELEVANCE_STATES, card.relevance.state) || !text(card.relevance.statement)) {
    return "A story's relevance is not readable.";
  }
  return timesProblem(card) ?? countsProblem(card.coverage) ?? signalsProblem(card.signals);
}

const marked = (story: StoryCard) => story.signals.some((row) => row.signal === "priority");

function relevanceProblem(value: unknown): string | null {
  if (!record(value) || !oneOf(RELEVANCE_STATES, value.state) || !text(value.statement) ||
      !(value.basis === null || oneOf(RELEVANCE_BASES, value.basis)) || !textOrNull(value.basis_label) ||
      !textOrNull(value.explanation) || !textOrNull(value.change) || !Array.isArray(value.dimensions) ||
      !value.dimensions.every((row) => record(row) && oneOf(DIMENSIONS, row.dimension) && text(row.how)) ||
      !texts(value.missing) || !(value.current === null || flag(value.current))) {
    return "The story's relevance is not readable.";
  }
  if ((value.basis === null) !== (value.basis_label === null)) return "The story's relevance names no one who decided.";
  const explained = value.state === "relevant" || value.state === "outside_scope" || value.state === "insufficient";
  if (explained !== (value.explanation !== null)) return "The story's relevance and its explanation disagree.";
  if ((value.state === "pending" || value.state === "restricted") !== (value.basis === null)) {
    return "The story's relevance and who decided it disagree.";
  }
  if (value.state !== "relevant" && (value.change !== null || value.dimensions.length > 0)) {
    return "A story not established as relevant shows economic dimensions.";
  }
  return null;
}

function topicCardProblem(topic: unknown): string | null {
  if (!record(topic) || !topicId(topic.topic_id) || !text(topic.title) || typeof topic.summary !== "string" ||
      !count(topic.developments) || !timeOrNull(topic.latest_at) || !textOrNull(topic.latest_title) ||
      !flag(topic.synthetic)) return "A topic is not readable.";
  return (topic.developments === 0) === (topic.latest_at === null) ? null : "A topic's developments disagree.";
}

function sourceRowProblem(row: unknown): string | null {
  return record(row) && typeof row.source === "string" && SOURCE_KEY.test(row.source) && text(row.publisher) &&
    text(row.name) && text(row.label) && oneOf(ROLES, row.role) && text(row.role_label) && oneOf(SOURCE_STATES, row.state) &&
    timeOrNull(row.last_success_at) && flag(row.stale) && count(row.reports) && oneOf(DISPLAYS, row.display) &&
    oneOf(MATERIAL, row.material) && typeof row.attribution === "string" && https(row.terms_url) &&
    flag(row.synthetic) ? null : "A news source is not readable.";
}

function storiesProblem(view: unknown): string | null {
  if (!record(view) || view.view_version !== STORIES_VIEW_VERSION || !oneOf(VIEWS, view.view) || !time(view.as_of) ||
      !record(view.rank) || view.rank.rank_version !== RANK_VERSION || !count(view.rank.hot_hours) ||
      !text(view.rank.statement) || !interestList(view.interests) || !texts(view.notes) || !text(view.statement)) {
    return "The stories are not readable.";
  }
  const bad = listProblem(view.stories, cardProblem) ?? listProblem(view.awaiting, cardProblem) ??
    listProblem(view.topics, topicCardProblem) ?? listProblem(view.sources, sourceRowProblem);
  if (bad) return bad;
  const names = (view.sources as SourceRow[]).map((row) => row.name);
  if (new Set(names).size !== names.length) return "Two news sources have the same name.";
  const left = view.left_out;
  if (!record(left) || !count(left.outside_scope) || !count(left.older_unassessed) || !text(left.statement)) {
    return "What the stories leave out is not readable.";
  }
  const stories = view.stories as StoryCard[], awaiting = view.awaiting as StoryCard[];
  if (stories.some((story) => story.relevance.state !== "relevant" && !marked(story))) {
    return "The stories list one whose economic relevance is not established.";
  }
  if (awaiting.some((story) => !oneOf(AWAITING_STATES, story.relevance.state) || marked(story))) {
    return "The headlines awaiting an assessment list one that is not awaiting.";
  }
  if (view.view === "interests" && awaiting.length > 0) return "Your interests list headlines awaiting an assessment.";
  const ids = [...stories, ...awaiting].map((story) => story.story_id);
  if (new Set(ids).size !== ids.length) return "The stories list one story twice.";
  if (view.view === "interests" && (view.stories as StoryCard[]).some((story) =>
    !story.interests.some((slug) => (view.interests as Interest[]).includes(slug)))) {
    return "The stories by interests show one outside them.";
  }
  return null;
}

function contentProblem(content: unknown, used: Set<string>): string | null {
  if (!record(content) || !text(content.headline) || !text(content.summary) || !Array.isArray(content.facts) ||
      content.facts.length === 0 || !Array.isArray(content.implications) || !Array.isArray(content.themes) ||
      !texts(content.uncertainties) || !texts(content.missing)) return "The brief is not readable.";
  if (!content.facts.every((fact) => record(fact) && text(fact.text) && Array.isArray(fact.reports) &&
      fact.reports.length > 0 && fact.reports.every((entry) => typeof entry === "string" && used.has(entry)))) {
    return "A fact of the brief cites a report its material does not hold.";
  }
  if (!content.implications.every((row) => record(row) && text(row.text)) ||
      !content.themes.every((row) => record(row) && oneOf(THEME_KINDS, row.kind) && text(row.name) &&
        text(row.basis))) return "The brief's implications or themes are not readable.";
  return claimsProblem(content, used);
}

/** story-brief-0.4: a brief records claims and every fact names its own, or neither does. */
function claimsProblem(content: Record<string, unknown>, used: Set<string>): string | null {
  const facts = content.facts as Record<string, unknown>[];
  if (content.claims === undefined) {
    return facts.every((fact) => fact.claims === undefined) ? null
      : "A fact of the brief cites claims the brief does not record.";
  }
  const claims = content.claims;
  if (!Array.isArray(claims) || !claims.every((row, index) => record(row) && row.id === `k${index + 1}` &&
      oneOf(HOLDERS, row.holder) && text(row.holder_name) && oneOf(MODALITIES, row.modality) && text(row.quote) &&
      textOrNull(row.condition) && (row.modality !== "conditional" || row.condition !== null) && text(row.source) &&
      (!(row.source as string).startsWith("report:") || used.has((row.source as string).slice(7))))) {
    return "The brief's claims are not readable.";
  }
  const ids = new Set((claims as { id: string }[]).map((row) => row.id));
  return facts.every((fact) => texts(fact.claims) && (fact.claims as string[]).every((id) => ids.has(id))) ? null
    : "A fact of the brief cites a claim the brief does not record.";
}

/** The "Who says what" view: present exactly when the content records claims, and saying the same of each. */
function claimsViewProblem(view: unknown, content: Record<string, unknown>): string | null {
  if (content.claims === undefined) return view === undefined ? null : "The brief shows claims it does not record.";
  const claims = content.claims as BriefClaim[];
  const facts = content.facts as { claims: string[] }[];
  if (!record(view) || view.claims_version !== CLAIMS_VERSION || !text(view.statement) ||
      !Array.isArray(view.claims) || view.claims.length !== claims.length ||
      !view.claims.every((row, index) => {
        const claim = claims[index];
        const reports = claim.source.startsWith("report:") ? [claim.source.slice(7)] : [];
        const citedFacts = facts.flatMap((fact, n) => fact.claims.includes(claim.id) ? [n + 1] : []);
        return record(row) && row.id === claim.id && row.holder === claim.holder &&
          row.holder_name === claim.holder_name && row.modality === claim.modality &&
          row.quote === claim.quote && row.condition === claim.condition && row.source === claim.source &&
          text(row.holder_label) && text(row.modality_label) && textOrNull(row.link) &&
          Array.isArray(row.reports) && row.reports.length === reports.length &&
          row.reports.every((entry, n) => entry === reports[n]) &&
          Array.isArray(row.facts) && row.facts.length === citedFacts.length &&
          row.facts.every((number, n) => number === citedFacts[n]);
      })) {
    return "The brief's claims are not readable.";
  }
  return null;
}

function briefProblem(brief: unknown): string | null {
  if (!record(brief) || brief.brief_version !== BRIEF_VERSION || !count(brief.version) || brief.version < 1 ||
      !oneOf(BRIEF_METHODS, brief.method) || !text(brief.method_label) || !time(brief.prepared_at) ||
      !time(brief.published_at) || !count(brief.reports_since) || !flag(brief.synthetic) || !text(brief.statement) ||
      !oneOf(AUTHORSHIPS, brief.authorship) || !record(brief.review) || !oneOf(REVIEW_STATES, brief.review.state) ||
      !text(brief.review.statement) || !flag(brief.current) || brief.current !== (brief.update_note === null) ||
      !textOrNull(brief.update_note)) {
    return "The brief is not readable.";
  }
  if (AUTHORSHIP_OF[brief.method as (typeof BRIEF_METHODS)[number]] !== brief.authorship ||
      (brief.authorship === "editor") !== (brief.review.state === "written_by_editor")) {
    return "The brief's authorship and its review disagree.";
  }
  const material = brief.material;
  if (!record(material) || !oneOf(COVERAGES, material.coverage) || !text(material.statement) ||
      !Array.isArray(material.reports) || material.reports.length === 0 ||
      !material.reports.every((row) => record(row) && entryId(row.entry_id) && text(row.publisher) &&
        text(row.title)) || !Array.isArray(material.not_used) ||
      !material.not_used.every((row) => record(row) && text(row.publisher) && text(row.title) && text(row.reason))) {
    return "The brief's material is not readable.";
  }
  if ((brief.method === "synthetic") !== brief.synthetic) return "The brief's synthetic mark disagrees.";
  const history = brief.revisions;
  if (!record(history) || !Array.isArray(history.earlier) || !texts(history.changes) ||
      !(history.updated_at === null || time(history.updated_at)) ||
      (history.earlier.length === 0) !== (history.changes.length === 0) ||
      (history.earlier.length === 0) !== (history.updated_at === null) ||
      !history.earlier.every((row) => record(row) && count(row.version) && row.version >= 1 &&
        row.version !== brief.version && time(row.published_at) && time(row.prepared_at) &&
        oneOf(BRIEF_METHODS, row.method) && AUTHORSHIP_OF[row.method as (typeof BRIEF_METHODS)[number]] ===
        row.authorship && (row.recorded_as === null || (oneOf(BRIEF_METHODS, row.recorded_as) &&
          row.recorded_as !== row.method)) && (row.corrects === null || (count(row.corrects) && row.corrects >= 1 &&
          row.corrects < row.version)) && text(row.headline) && text(row.summary) && count(row.reports) &&
        flag(row.explained))) {
    return "The brief's earlier versions are not readable.";
  }
  if (brief.context_statement !== undefined && (!textOrNull(brief.context_statement) ||
      (brief.context_statement === null && record(brief.economics) && Array.isArray(brief.economics.context) &&
       brief.economics.context.length > 0))) {
    return "The brief does not say what context its explanation read.";
  }
  const used = new Set((material.reports as { entry_id: string }[]).map((row) => row.entry_id));
  return contentProblem(brief.content, used) ??
    claimsViewProblem(brief.claims, brief.content as Record<string, unknown>) ??
    (brief.economics === null ? null : economicsProblem(brief.economics, used));
}

function textStateProblem(value: unknown): string | null {
  if (!record(value) || !oneOf(TEXT_STATES, value.state) || !(value.characters === null || count(value.characters)) ||
      !timeOrNull(value.retrieved_at) || !textOrNull(value.partial_reason) || !textOrNull(value.detail)) {
    return "A source's publication text state is not readable.";
  }
  const held = value.state === "full_text" || value.state === "partial_text";
  if (held !== (value.characters !== null && value.retrieved_at !== null)) return "A source's text state disagrees.";
  return (value.state === "partial_text") === (value.partial_reason !== null) ? null
    : "A source's partial text does not say why.";
}

function materialTextProblem(value: unknown): string | null {
  if (value === undefined) return null;
  return record(value) && (value.state === "full_text" || value.state === "partial_text") &&
    typeof value.text_sha256 === "string" && SHA.test(value.text_sha256) && count(value.characters) &&
    value.characters > 0 && time(value.retrieved_at) && https(value.url) && text(value.extractor) &&
    (value.state === "partial_text") === text(value.partial_reason) ? null : "A report's publication text is not readable.";
}

function storySourceProblem(row: unknown): string | null {
  if (!record(row) || !entryId(row.entry_id) || !text(row.publisher) || !oneOf(ROLES, row.role) ||
      !text(row.role_label) || !text(row.kind) || !text(row.title) || !flag(row.title_shortened) ||
      !textOrNull(row.excerpt) || !flag(row.excerpt_shortened) || !https(row.link) || !time(row.first_seen_at) ||
      !(row.listing === "current" || row.listing === "retained") || !flag(row.stale) ||
      typeof row.attribution !== "string" || !flag(row.synthetic) || !count(row.unit) || row.unit < 1 ||
      !texts(row.counted_together_because) || !oneOf(USES, row.use)) return "A source of the story is not readable.";
  return textStateProblem(row.text) ?? publishedProblem(row.published);
}

function deeperProblem(deeper: unknown): string | null {
  if (!record(deeper) || !flag(deeper.available) || !count(deeper.material_reports) || !textOrNull(deeper.reason)) {
    return "The story's deeper analysis state is not readable.";
  }
  return deeper.available === (deeper.reason === null) ? null : "The deeper analysis state and its reason disagree.";
}

function storyPageProblem(story: unknown): string | null {
  if (!record(story) || story.view_version !== STORY_VIEW_VERSION || !storyId(story.story_id) ||
      !storyId(story.requested_id) || !flag(story.merged) || !text(story.title) ||
      !(story.title_basis === "editors" || story.title_basis === "first_report") || !interestList(story.interests) ||
      !flag(story.older) || !flag(story.stale) || !flag(story.synthetic) || !oneOf(BRIEF_STATES, story.brief_state) ||
      !textOrNull(story.brief_note) || !text(story.statement) || !record(story.coverage) ||
      story.coverage.coverage_version !== COVERAGE_VERSION || !Array.isArray(story.related) ||
      !story.related.every((row) => record(row) && storyId(row.story_id) && text(row.title) && time(row.first_at) &&
        oneOf(TIME_BASES, row.first_basis) &&
        textOrNull(row.label) && topicId(row.topic_id))) return "The story is not readable.";
  if (story.merged !== (story.story_id !== story.requested_id)) return "The story's address and its own disagree.";
  const units = (story.coverage as Record<string, unknown>).units;
  if (!Array.isArray(units) || !units.every((unit) => record(unit) && oneOf(INDEPENDENCE, unit.independence) &&
      texts(unit.uncertain_because) && (unit.independence === "unverified") === (unit.uncertain_because.length > 0))
      || !Array.isArray((story.coverage as Record<string, unknown>).possible_shared_origins)) {
    return "The story's reporting origins are not readable.";
  }
  const bad = timesProblem(story) ?? countsProblem(story.coverage) ?? signalsProblem(story.signals) ??
    listProblem(story.sources, storySourceProblem) ?? listProblem(story.topics, topicCardProblem) ??
    deeperProblem(story.deeper) ?? relevanceProblem(story.relevance) ??
    (story.brief === null ? null : briefProblem(story.brief)) ?? explanationProblem(story.explanation);
  if (bad) return bad;
  const explained = (story.brief as Brief | null)?.economics?.status === "explained";
  if (((story.explanation as Explanation).state === "ready") && !explained) {
    return "The story says its explanation is ready and shows none.";
  }
  if ((story.relevance as Relevance).state === "outside_scope" && (story.deeper as Deeper).available) {
    return "A story outside the economic news offers a deeper analysis.";
  }
  if ((story.brief_state === "published") !== (story.brief !== null)) return "The story's brief and its state disagree.";
  if ((story.brief_state === "published") === (story.brief_note !== null)) return "The story's brief note disagrees.";
  const sources = story.sources as StorySource[];
  if (sources.length === 0) return "A story lists no source.";
  if (sources.length !== (story.coverage as unknown as Coverage).reports) return "The story counts other sources.";
  const brief = story.brief as Brief | null;
  if (brief && sources.some((row) => (row.use === "material") !==
      brief.material.reports.some((used) => used.entry_id === row.entry_id))) {
    return "The story's sources disagree with its brief's material.";
  }
  return null;
}

function topicPageProblem(topic: unknown): string | null {
  const bad = topicCardProblem(topic);
  if (bad) return bad;
  const page = topic as Record<string, unknown>;
  if (page.view_version !== TOPICS_VIEW_VERSION || !text(page.statement) || !Array.isArray(page.timeline)) {
    return "The topic is not readable.";
  }
  return listProblem(page.timeline, (row) => cardProblem(row) ??
    (record(row) && textOrNull(row.label) ? null : "A development's label is not readable.")) ??
    (page.timeline.length === page.developments ? null : "The topic counts other developments.");
}

function materialProblem(material: unknown): string | null {
  if (!record(material) || !oneOf(COVERAGES, material.coverage) || !text(material.statement) ||
      !Array.isArray(material.reports) || !Array.isArray(material.not_used)) return "The material is not readable.";
  if (!material.reports.every((row) => record(row) && entryId(row.entry_id) && typeof row.version_sha256 === "string" &&
      SHA.test(row.version_sha256) && text(row.publisher) && oneOf(ROLES, row.role) && text(row.title) &&
      textOrNull(row.excerpt) && https(row.link) && (row.published === null || typeof row.published === "string") &&
      timeOrNull(row.published_utc) && typeof row.attribution === "string" && flag(row.synthetic) &&
      materialTextProblem(row.text) === null)) {
    return "A report of the material is not readable.";
  }
  const held = (material.reports as MaterialReport[]).filter((row) => row.text !== undefined);
  const textual = material.coverage === "full_text" || material.coverage === "partial_text";
  if (textual !== (held.length > 0) || (material.coverage === "full_text" &&
      (held.length !== material.reports.length || held.some((row) => row.text?.state !== "full_text")))) {
    return "The material's coverage disagrees with its texts.";
  }
  return material.not_used.every((row) => record(row) && entryId(row.entry_id) && text(row.publisher) &&
    text(row.title) && https(row.link) && text(row.reason)) ? null : "The material's left-out reports are not readable.";
}

function previewProblem(preview: unknown): string | null {
  if (!record(preview) || preview.deeper_version !== DEEPER_VERSION || !storyId(preview.story_id) ||
      !text(preview.title) || typeof preview.material_sha256 !== "string" || !SHA.test(preview.material_sha256) ||
      !text(preview.statement)) return "The deeper analysis preview is not readable.";
  const bad = deeperProblem(preview) ?? materialProblem(preview.material);
  if (bad) return bad;
  const source = preview.source;
  if (source !== null && (!record(source) || !text(source.headline) || !https(source.source_url) ||
      !time(source.published_at) || !count(source.characters) || !text(source.text) ||
      Array.from(source.text).length !== source.characters)) return "The deeper analysis's source is not readable.";
  if (preview.available !== (source !== null)) return "The deeper analysis's source and availability disagree.";
  const existing = preview.existing;
  if (existing !== null && (!record(existing) || typeof existing.source_id !== "string" ||
      !SOURCE_ID.test(existing.source_id) || !Array.isArray(existing.analyses) ||
      !existing.analyses.every((row) => record(row) && text(row.analysis_id) && oneOf(EFFORTS, row.effort)))) {
    return "Your earlier deeper analysis is not readable.";
  }
  return null;
}

export const readStories = (body: unknown) =>
  wrapped<{ contract: string; stories: StoriesView }>(body, (payload) => storiesProblem(payload.stories));
export const readStory = (body: unknown) =>
  wrapped<{ contract: string; story: StoryPage }>(body, (payload) => storyPageProblem(payload.story));
export const readTopics = (body: unknown) =>
  wrapped<{ contract: string; topics: TopicsView }>(body, (payload) => {
    const topics = payload.topics;
    return record(topics) && topics.view_version === TOPICS_VIEW_VERSION && time(topics.as_of) &&
      texts(topics.notes) && text(topics.statement) ? listProblem(topics.topics, topicCardProblem)
      : "The topics are not readable.";
  });
export const readTopic = (body: unknown) =>
  wrapped<{ contract: string; topic: TopicPage }>(body, (payload) => topicPageProblem(payload.topic));
export const readDeeperPreview = (body: unknown) =>
  wrapped<{ contract: string; deeper: DeeperPreview }>(body, (payload) => previewProblem(payload.deeper));
export const readDeeperDone = (body: unknown) =>
  wrapped<{ contract: string; deeper: DeeperDone; created: boolean }>(body, (payload) => {
    const done = payload.deeper;
    if (!flag(payload.created) || !record(done) || done.deeper_version !== DEEPER_VERSION || !storyId(done.story_id) ||
        !flag(done.created_source) || !flag(done.created_analysis) || !record(done.source) ||
        typeof done.source.source_id !== "string" || !SOURCE_ID.test(done.source.source_id) || !record(done.analysis) ||
        typeof done.analysis.analysis_id !== "string") return "The deeper analysis reply is not readable.";
    if (payload.created !== (done.created_source || done.created_analysis)) {
      return "The deeper analysis reply says something was new and nothing was.";
    }
    return (done.analysis as unknown as Analysis).source?.source_id === done.source.source_id ? null
      : "The prepared analysis is of another source.";
  });

// ---------------------------------------------------------------- requests

/** The stories routes' request helpers, bound to a fetch implementation and, for a signed-in page, its account. */
export function storiesApi(fetcher: Fetcher = (input, init) => fetch(input, init),
                           binding: AccountBinding | null = null) {
  const account = binding?.account ?? null;
  const get = <T>(url: string, read: (body: unknown) => Read<T>): Promise<Reply<T>> =>
    request(fetcher, "GET", url, undefined, USER_HEADER, read, undefined, account);
  const id = (value: string) => encodeURIComponent(value);
  return {
    stories: (view: View) => get(`/api/user/news/stories?view=${view}`, readStories),
    story: (storyId: string) => get(`/api/user/news/stories/${id(storyId)}`, readStory),
    topics: () => get("/api/user/news/topics", readTopics),
    topic: (topicId: string) => get(`/api/user/news/topics/${id(topicId)}`, readTopic),
    deeper: (storyId: string) => get(`/api/user/news/stories/${id(storyId)}/deeper`, readDeeperPreview),
    goDeeper: (storyId: string, materialSha256: string, effort: Effort) =>
      request(fetcher, "POST", `/api/user/news/stories/${id(storyId)}/deeper`,
              { material_sha256: materialSha256, effort }, USER_HEADER, readDeeperDone, undefined, account),
  };
}

export type StoriesApi = ReturnType<typeof storiesApi>;

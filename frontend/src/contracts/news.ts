// Current news, interests, publication import, research checks and limits: the user-api-0.4 routes of
// docs/news-usage-contract.md (interests news-interests-0.2 since user-api-0.5). Owned by the logic conversation, like src/contracts/user.ts; the Client imports it and
// never edits it. The news, search, import and quality payloads are the data owner's (user_news, publication_import,
// research_quality); the envelopes, interests, request keys and limits are this contract's.
//
// Every reader is fail-closed: a payload missing a required field, carrying an unknown state or contradicting itself
// is refused as unreadable rather than shown. A feed's excerpt or headline is discovery metadata, never a publication:
// nothing here turns an entry into a source; only a confirmed import or a pasted source is one. No read here contacts a
// publisher or a model. The request helpers only describe requests; nothing is sent until a caller invokes one, none
// retries, and helpers made with an account name it on every request (account binding).
import {
  DAY, OPERATIONS, SHA, SOURCE_ID, USER_HEADER, count, listProblem, oneOf, record, request, sourceProblem, text,
  texts, time, wrapped, type AccountBinding, type Fetcher, type Operation, type Read, type Reply, type Source,
} from "./user.ts";

export const NEWS_VIEW_VERSION = "user-news-view-0.1";
export const NEWS_SEARCH_VERSION = "user-news-search-0.1";
export const INTERESTS_VERSION = "news-interests-0.2";
export const IMPORT_VERSION = "publication-import-0.1";
export const QUALITY_VERSION = "research-quality-0.3";

export const NEWS_SOURCES = ["fed-monetary", "bls-empsit", "bls-cpi", "eia-todayinenergy", "wto-news"] as const;
/** news-interests-0.2: the five official feeds' topics, then three for the publisher feeds (docs/news-stories-contract.md). */
export const INTERESTS = ["monetary-policy", "employment", "inflation", "energy", "trade", "markets", "technology",
  "companies"] as const;
export const SOURCE_STATES = ["never_refreshed", "ok", "failed", "not_requested", "unreadable"] as const;
export const ATTEMPT_OUTCOMES = ["ok", "failed", "not_requested"] as const;
export const PUBLISHED_STATES = ["stated", "date_only", "unstated"] as const;
export const ENTRY_LISTINGS = ["current", "retained"] as const;
export const SEARCH_LISTINGS = ["current", "all"] as const;
export const SCOPES = ["interests", "all"] as const;
export const TOPIC_BASES = ["source", "terms"] as const;
export const TERM_FIELDS = ["title", "excerpt"] as const;
export const IMPORT_SUPPORT = ["supported", "unsupported", "imported"] as const;
export const IMPORT_STATES = ["ready", "confirming", "confirmed", "interrupted", "unreadable"] as const;
export const RETRIEVALS = ["fetched", "reused"] as const;
export const LIMITS_STATES = ["set", "no_policy"] as const;
/** A search query's bounds; the server checks them again. */
export const SEARCH_RULES = { maxCharacters: 200, maxWords: 8, maxResults: 100 } as const;
export const REQUEST_KEY = /^[A-Za-z0-9_-]{8,80}$/;

export type NewsSourceKey = (typeof NEWS_SOURCES)[number];
export type Interest = (typeof INTERESTS)[number];
export type SourceState = (typeof SOURCE_STATES)[number];
export type Scope = (typeof SCOPES)[number];
export type SearchListing = (typeof SEARCH_LISTINGS)[number];
export type ImportState = (typeof IMPORT_STATES)[number];

// ---------------------------------------------------------------- payload types

export interface NewsSource {
  source: NewsSourceKey; label: string; publisher: string; interest: Interest; kind: string; attribution: string;
  catalogue_url: string; terms_url: string; state: SourceState; last_success_at: string | null;
  last_attempt: { at: string; outcome: (typeof ATTEMPT_OUTCOMES)[number]; detail: string | null } | null;
  note: string | null; stale: boolean; entries: number; importable: boolean;
}
export interface Published {
  state: (typeof PUBLISHED_STATES)[number]; as_stated: string | null; element: string | null; utc: string | null;
  date: string | null; note: string | null;
}
export interface Topic {
  interest: Interest; basis: (typeof TOPIC_BASES)[number];
  terms: { term: string; field: (typeof TERM_FIELDS)[number] }[];
}
export interface NewsEntry {
  entry_id: string; version_sha256: string; source: NewsSourceKey; title: string; title_shortened: boolean;
  excerpt: string | null; excerpt_shortened: boolean; excerpt_repeats_title: boolean; link: string;
  published: Published; first_retrieved_at: string; last_retrieved_at: string;
  listing: (typeof ENTRY_LISTINGS)[number]; stale: boolean; topics: Topic[]; matches_interests: boolean;
  import: { state: (typeof IMPORT_SUPPORT)[number]; reason: string | null; source_ids: string[] };
  /** user-api-0.5: the story this entry is grouped into (its headline opens that story), or null when in none yet. */
  story_id: string | null;
}
export interface NewsView {
  view_version: typeof NEWS_VIEW_VERSION; vocabulary_version: typeof INTERESTS_VERSION; scope: Scope;
  interests: Interest[]; sources: NewsSource[]; entries: NewsEntry[]; notes: string[]; statement: string;
}
export interface InterestTerms { interest: Interest; label: string; sources: NewsSourceKey[]; terms: string[] }
export interface Interests {
  vocabulary_version: typeof INTERESTS_VERSION; rule: string; vocabulary: InterestTerms[]; selected: Interest[];
  version: number | null; saved_at: string | null;
}
export interface SearchForm {
  query: string; interests: Interest[] | null; sources: NewsSourceKey[] | null; listing: SearchListing;
  request_key: string;
}
export interface SearchDone {
  query: string; words: string[]; interests: Interest[] | null; sources: NewsSourceKey[] | null;
  listing: SearchListing; matched: number; shown: number; limit: number;
}
/** One counted operation's figures, as the server holds them after the request. */
export interface QuotaNow { operation: Operation; label: string; limit: number | null; used: number; remaining: number | null }
export interface ImportPreview {
  import_version: typeof IMPORT_VERSION; import_id: string; state: ImportState; problem: string | null;
  created_at: string;
  entry: { entry_id: string; version_sha256: string; source: NewsSourceKey; title: string; link: string;
           publisher: string; attribution: string };
  publication: { url: string; retrieved_at: string; retrieval: (typeof RETRIEVALS)[number]; bytes: number;
                 sha256: string; last_modified: string | null; extractor: string; terms_url: string };
  proposed_source: { headline: string; source_url: string; published_at: string; published_basis: string;
                     characters: number; paragraphs: number; text_sha256: string; text: string | null };
  left_out: { kind: string; text: string }[]; linked_documents: { title: string; url: string }[];
  source_id: string | null; statements: string[];
}
export interface Limits {
  state: (typeof LIMITS_STATES)[number]; detail: string | null; policy_version: string | null; day: string;
  timezone: string; resets_at: string; operations: QuotaNow[];
  storage: { sources: { used: number; limit: number | null }; source_bytes: { used: number; limit: number | null } };
  rate: { requests_per_minute: number | null; concurrent_requests: number | null };
}
export interface QualityFinding { check: string; level: "flagged"; where: string; detail: string; rule: string }
export interface Quality {
  rubric_version: typeof QUALITY_VERSION; rejected: never[]; rejected_note: string; findings: QualityFinding[];
  flagged: number; checks: Record<string, string>; human_review: string[]; statement: string;
}

// ---------------------------------------------------------------- readers

const ENTRY_ID = /^([a-z]+(?:-[a-z]+)*):[0-9a-f]{20}$/;
const IMPORT_ID = /^imp-[0-9a-f]{16}$/;
const https = (value: unknown): value is string => {
  if (typeof value !== "string") return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
};
const flag = (value: unknown): value is boolean => typeof value === "boolean";
const textOrNull = (value: unknown) => value === null || text(value);
const stringOrNull = (value: unknown) => value === null || typeof value === "string";
const timeOrNull = (value: unknown) => value === null || time(value);
const distinct = (values: unknown[]) => new Set(values).size === values.length;
const interestList = (value: unknown): value is Interest[] =>
  Array.isArray(value) && value.every((item) => oneOf(INTERESTS, item)) && distinct(value);
const sourceList = (value: unknown): value is NewsSourceKey[] =>
  Array.isArray(value) && value.length > 0 && value.every((item) => oneOf(NEWS_SOURCES, item)) && distinct(value);

function newsSourceProblem(source: unknown): string | null {
  if (!record(source) || !oneOf(NEWS_SOURCES, source.source) || !text(source.label) || !text(source.publisher) ||
      !oneOf(INTERESTS, source.interest) || !text(source.kind) || typeof source.attribution !== "string" ||
      !https(source.catalogue_url) || !https(source.terms_url) || !oneOf(SOURCE_STATES, source.state) ||
      !timeOrNull(source.last_success_at) || !textOrNull(source.note) || !flag(source.stale) ||
      !count(source.entries) || !flag(source.importable)) return "A news source is not readable.";
  const attempt = source.last_attempt;
  if (attempt !== null && (!record(attempt) || !time(attempt.at) || !oneOf(ATTEMPT_OUTCOMES, attempt.outcome) ||
      !textOrNull(attempt.detail))) return "A news source's last retrieval is not readable.";
  if ((source.state === "ok" || source.stale) && source.last_success_at === null) {
    return "A news source shows entries without a successful retrieval.";
  }
  return null;
}

export function publishedProblem(published: unknown): string | null {
  if (!record(published) || !oneOf(PUBLISHED_STATES, published.state) || !stringOrNull(published.as_stated) ||
      !stringOrNull(published.element) || !timeOrNull(published.utc) || !textOrNull(published.note) ||
      !(published.date === null || (typeof published.date === "string" && DAY.test(published.date)))) {
    return "An entry's publication time is not readable.";
  }
  const stated = published.state === "stated", dated = published.date !== null;
  if (stated !== (published.utc !== null) || (published.state === "unstated") === dated) {
    return "An entry's publication time contradicts its state.";
  }
  return null;
}

function topicProblem(topic: unknown): string | null {
  if (!record(topic) || !oneOf(INTERESTS, topic.interest) || !oneOf(TOPIC_BASES, topic.basis) ||
      !Array.isArray(topic.terms) || !topic.terms.every((term) => record(term) && text(term.term) &&
        oneOf(TERM_FIELDS, term.field))) return "An entry's topic is not readable.";
  return topic.basis === "terms" && topic.terms.length === 0 ? "A topic found by its terms names none." : null;
}

export function entryProblem(entry: unknown): string | null {
  if (!record(entry) || typeof entry.entry_id !== "string" || !oneOf(NEWS_SOURCES, entry.source) ||
      ENTRY_ID.exec(entry.entry_id)?.[1] !== entry.source || typeof entry.version_sha256 !== "string" ||
      !SHA.test(entry.version_sha256) || !text(entry.title) || !flag(entry.title_shortened) ||
      !stringOrNull(entry.excerpt) || !flag(entry.excerpt_shortened) || !flag(entry.excerpt_repeats_title) ||
      !https(entry.link) || !time(entry.first_retrieved_at) || !time(entry.last_retrieved_at) ||
      !oneOf(ENTRY_LISTINGS, entry.listing) || !flag(entry.stale) || !flag(entry.matches_interests) ||
      !Array.isArray(entry.topics) ||
      !(entry.story_id === null || (typeof entry.story_id === "string" && /^story-[0-9a-f]{16}$/.test(entry.story_id)))) {
    return "A news entry is not readable.";
  }
  const bad = publishedProblem(entry.published) ?? listProblem(entry.topics, topicProblem);
  if (bad) return bad;
  const imported = entry.import;
  if (!record(imported) || !oneOf(IMPORT_SUPPORT, imported.state) || !textOrNull(imported.reason) ||
      !Array.isArray(imported.source_ids) || !imported.source_ids.every((id) => typeof id === "string" &&
        SOURCE_ID.test(id))) return "A news entry's import is not readable.";
  if ((imported.state === "imported") !== (imported.source_ids.length > 0)) {
    return "A news entry's import state contradicts its sources.";
  }
  if (imported.state === "unsupported" && imported.reason === null) return "An entry that cannot be imported says why.";
  return null;
}

function viewProblem(view: unknown): string | null {
  if (!record(view) || view.view_version !== NEWS_VIEW_VERSION || view.vocabulary_version !== INTERESTS_VERSION ||
      !oneOf(SCOPES, view.scope) || !interestList(view.interests) || !Array.isArray(view.sources) ||
      !Array.isArray(view.entries) || !texts(view.notes) || !text(view.statement)) return "The news is not readable.";
  const bad = listProblem(view.sources, newsSourceProblem) ?? listProblem(view.entries, entryProblem);
  if (bad) return bad;
  const known = new Set((view.sources as NewsSource[]).map((source) => source.source));
  if (!distinct([...known]) || known.size !== view.sources.length) return "The news lists a source twice.";
  const entries = view.entries as NewsEntry[];
  if (entries.some((entry) => !known.has(entry.source))) return "An entry comes from a source the news does not list.";
  if (view.scope === "interests" && entries.some((entry) => !entry.matches_interests)) {
    return "The news by interests shows an entry outside them.";
  }
  return null;
}

function interestsProblem(interests: unknown): string | null {
  if (!record(interests) || interests.vocabulary_version !== INTERESTS_VERSION || !text(interests.rule) ||
      !Array.isArray(interests.vocabulary) || !interestList(interests.selected) ||
      !(interests.version === null || (count(interests.version) && interests.version >= 1)) ||
      !timeOrNull(interests.saved_at)) return "The interests are not readable.";
  if ((interests.version === null) !== (interests.saved_at === null)) return "The interests' version and time disagree.";
  const vocabulary = interests.vocabulary;
  if (!vocabulary.every((row) => record(row) && oneOf(INTERESTS, row.interest) && text(row.label) &&
      Array.isArray(row.sources) && row.sources.every((source) => oneOf(NEWS_SOURCES, source)) && texts(row.terms)) ||
      !distinct(vocabulary.map((row) => (row as InterestTerms).interest))) return "The interest vocabulary is not readable.";
  const order = vocabulary.map((row) => (row as InterestTerms).interest);
  const selected = interests.selected as Interest[];
  if (selected.some((slug) => !order.includes(slug)) ||
      selected.some((slug, index) => index > 0 && order.indexOf(slug) < order.indexOf(selected[index - 1]))) {
    return "The selected interests are not in the vocabulary's order.";
  }
  return null;
}

/** The selection a 409 interests_changed carries, or the interests of a reply. */
export const readInterestsState = (value: unknown): Read<Interests> => {
  const problem = interestsProblem(value);
  return problem ? { ok: false, problem } : { ok: true, value: value as Interests };
};

function quotaNowProblem(quota: unknown): string | null {
  if (!record(quota) || !oneOf(OPERATIONS, quota.operation) || !text(quota.label) || !count(quota.used) ||
      !(quota.limit === null || count(quota.limit)) || !(quota.remaining === null || count(quota.remaining))) {
    return "A limit is not readable.";
  }
  if ((quota.limit === null) !== (quota.remaining === null)) return "A limit and its remainder disagree.";
  if (quota.limit !== null && quota.remaining !== Math.max(0, (quota.limit as number) - quota.used)) {
    return "A limit's remainder does not follow from its limit and use.";
  }
  return null;
}

function limitsProblem(limits: unknown): string | null {
  if (!record(limits) || !oneOf(LIMITS_STATES, limits.state) || !textOrNull(limits.detail) ||
      !textOrNull(limits.policy_version) || typeof limits.day !== "string" || !DAY.test(limits.day) ||
      !text(limits.timezone) || !time(limits.resets_at) || !Array.isArray(limits.operations)) {
    return "The limits are not readable.";
  }
  const bad = listProblem(limits.operations, quotaNowProblem);
  if (bad) return bad;
  const operations = limits.operations as QuotaNow[];
  if (JSON.stringify(operations.map((row) => row.operation)) !== JSON.stringify(OPERATIONS)) {
    return "The limits do not list every counted operation in order.";
  }
  const storage = limits.storage, rate = limits.rate;
  const held = (value: unknown) => record(value) && count(value.used) && (value.limit === null || count(value.limit));
  if (!record(storage) || !held(storage.sources) || !held(storage.source_bytes) || !record(rate) ||
      !(rate.requests_per_minute === null || count(rate.requests_per_minute)) ||
      !(rate.concurrent_requests === null || count(rate.concurrent_requests))) return "The limits are not readable.";
  const set = limits.state === "set";
  const figures = [...operations.map((row) => row.limit), (storage.sources as { limit: unknown }).limit,
    (storage.source_bytes as { limit: unknown }).limit, rate.requests_per_minute, rate.concurrent_requests];
  if (set ? figures.some((value) => value === null) || limits.policy_version === null
    : figures.some((value) => value !== null) || limits.policy_version !== null || limits.detail === null) {
    return "The limits contradict their state.";
  }
  return null;
}

export function previewProblem(preview: unknown): string | null {
  if (!record(preview) || preview.import_version !== IMPORT_VERSION || typeof preview.import_id !== "string" ||
      !IMPORT_ID.test(preview.import_id) || !oneOf(IMPORT_STATES, preview.state) || !textOrNull(preview.problem) ||
      !time(preview.created_at) || !texts(preview.statements) ||
      !(preview.source_id === null || (typeof preview.source_id === "string" && SOURCE_ID.test(preview.source_id)))) {
    return "The import is not readable.";
  }
  const entry = preview.entry, publication = preview.publication, proposed = preview.proposed_source;
  if (!record(entry) || typeof entry.entry_id !== "string" || !oneOf(NEWS_SOURCES, entry.source) ||
      ENTRY_ID.exec(entry.entry_id)?.[1] !== entry.source || typeof entry.version_sha256 !== "string" ||
      !SHA.test(entry.version_sha256) || !text(entry.title) || !https(entry.link) || !text(entry.publisher) ||
      typeof entry.attribution !== "string") return "The import's entry is not readable.";
  if (!record(publication) || !https(publication.url) || !time(publication.retrieved_at) ||
      !oneOf(RETRIEVALS, publication.retrieval) || !count(publication.bytes) || typeof publication.sha256 !== "string" ||
      !SHA.test(publication.sha256) || !stringOrNull(publication.last_modified) || !text(publication.extractor) ||
      !https(publication.terms_url)) return "The import's publication is not readable.";
  if (!record(proposed) || !text(proposed.headline) || !https(proposed.source_url) || !time(proposed.published_at) ||
      !text(proposed.published_basis) || !count(proposed.characters) || !count(proposed.paragraphs) ||
      typeof proposed.text_sha256 !== "string" || !SHA.test(proposed.text_sha256) || !stringOrNull(proposed.text)) {
    return "The import's proposed source is not readable.";
  }
  if (!Array.isArray(preview.left_out) || !preview.left_out.every((row) => record(row) && text(row.kind) &&
        typeof row.text === "string") ||
      !Array.isArray(preview.linked_documents) || !preview.linked_documents.every((row) => record(row) &&
        typeof row.title === "string" && typeof row.url === "string")) return "The import's left-out text is not readable.";
  if ((preview.state === "confirmed") !== (preview.source_id !== null)) return "The import's state and source disagree.";
  if ((preview.state === "unreadable") !== (proposed.text === null) || (preview.state === "unreadable") !==
      (preview.problem !== null)) return "The import's state and text disagree.";
  if (typeof proposed.text === "string" && Array.from(proposed.text).length !== proposed.characters) {
    return "The import's text does not have the characters it states.";
  }
  return null;
}

function qualityProblem(quality: unknown): string | null {
  if (quality === null) return null;
  if (!record(quality) || quality.rubric_version !== QUALITY_VERSION || !Array.isArray(quality.rejected) ||
      quality.rejected.length !== 0 || !text(quality.rejected_note) || !Array.isArray(quality.findings) ||
      !count(quality.flagged) || !record(quality.checks) || !texts(quality.human_review) || !text(quality.statement) ||
      !Object.values(quality.checks).every(text)) return "The research checks are not readable.";
  const findings = quality.findings;
  if (!findings.every((finding) => record(finding) && text(finding.check) && finding.level === "flagged" &&
      text(finding.where) && text(finding.detail) && text(finding.rule))) return "A research check is not readable.";
  return quality.flagged === findings.length ? null : "The research checks' count disagrees with their findings.";
}

export const readNews = (body: unknown) =>
  wrapped<{ contract: string; news: NewsView }>(body, (payload) => viewProblem(payload.news));
export const readInterests = (body: unknown) =>
  wrapped<{ contract: string; interests: Interests }>(body, (payload) => interestsProblem(payload.interests));
export const readInterestsSaved = (body: unknown) =>
  wrapped<{ contract: string; interests: Interests; changed: boolean }>(body, (payload) =>
    flag(payload.changed) ? interestsProblem(payload.interests) : "The reply does not say whether anything changed.");
export const readSearch = (body: unknown) =>
  wrapped<{ contract: string; view_version: string; search: SearchDone; entries: NewsEntry[]; statement: string;
            counted: boolean; quota: QuotaNow }>(body, (payload) => {
    const search = payload.search;
    if (payload.view_version !== NEWS_SEARCH_VERSION || !flag(payload.counted) || !text(payload.statement) ||
        !record(search) || !text(search.query) || !texts(search.words) || search.words.length === 0 ||
        !(search.interests === null || interestList(search.interests)) ||
        !(search.sources === null || sourceList(search.sources)) || !oneOf(SEARCH_LISTINGS, search.listing) ||
        !count(search.matched) || !count(search.shown) || !count(search.limit)) return "The search is not readable.";
    const bad = listProblem(payload.entries, entryProblem) ?? quotaNowProblem(payload.quota);
    if (bad) return bad;
    if (search.shown !== Math.min(search.matched, search.limit) || (payload.entries as unknown[]).length !== search.shown) {
      return "The search shows another number of entries than it states.";
    }
    return (payload.quota as QuotaNow).operation === "search" ? null : "The search's limit is another operation's.";
  });
export const readImportCreated = (body: unknown) =>
  wrapped<{ contract: string; import: ImportPreview; created: boolean; quota: QuotaNow }>(body, (payload) =>
    !flag(payload.created) ? "The reply does not say whether the import was new."
      : previewProblem(payload.import) ?? quotaNowProblem(payload.quota) ??
        ((payload.quota as QuotaNow).operation === "import" ? null : "The import's limit is another operation's."));
export const readImport = (body: unknown) =>
  wrapped<{ contract: string; import: ImportPreview }>(body, (payload) => previewProblem(payload.import));
export const readImportConfirmed = (body: unknown) =>
  wrapped<{ contract: string; import: ImportPreview; source: Source; created: boolean }>(body, (payload) => {
    if (!flag(payload.created)) return "The reply does not say whether the source was new.";
    const bad = previewProblem(payload.import) ?? sourceProblem(payload.source);
    if (bad) return bad;
    const preview = payload.import as ImportPreview, source = payload.source as Source;
    return preview.state === "confirmed" && preview.source_id === source.source_id ? null
      : "The confirmed import names another source.";
  });
export const readLimits = (body: unknown) =>
  wrapped<{ contract: string; limits: Limits }>(body, (payload) => limitsProblem(payload.limits));
export const readQuality = (body: unknown) =>
  wrapped<{ contract: string; quality: Quality | null }>(body, (payload) =>
    "quality" in payload ? qualityProblem(payload.quality) : "The reply has no research checks.");

// ---------------------------------------------------------------- requests

/** A new key for one deliberate search: repeating a request with the same key and body is never counted twice. */
export const newRequestKey = (): string => `search-${crypto.randomUUID().replace(/-/g, "")}`;

/** The news routes' request helpers, bound to a fetch implementation and, for a signed-in page, its account. The
 * server refuses their writes without the account (428 account_binding_required). */
export function newsApi(fetcher: Fetcher = (input, init) => fetch(input, init), binding: AccountBinding | null = null) {
  const account = binding?.account ?? null;
  const get = <T>(url: string, read: (body: unknown) => Read<T>): Promise<Reply<T>> =>
    request(fetcher, "GET", url, undefined, USER_HEADER, read, undefined, account);
  const post = <T>(url: string, body: object, read: (body: unknown) => Read<T>): Promise<Reply<T>> =>
    request(fetcher, "POST", url, body, USER_HEADER, read, undefined, account);
  const id = (value: string) => encodeURIComponent(value);
  return {
    news: (scope: Scope) => get(`/api/user/news?scope=${scope}`, readNews),
    interests: () => get("/api/user/news/interests", readInterests),
    saveInterests: (interests: Interest[], expectedVersion: number | null) =>
      post("/api/user/news/interests", { interests, expected_version: expectedVersion }, readInterestsSaved),
    search: (form: SearchForm) => post("/api/user/news/searches", form, readSearch),
    previewImport: (entryId: string, versionSha256: string) =>
      post("/api/user/news/imports", { entry_id: entryId, version_sha256: versionSha256 }, readImportCreated),
    importPreview: (importId: string) => get(`/api/user/news/imports/${id(importId)}`, readImport),
    confirmImport: (importId: string, textSha256: string) =>
      post(`/api/user/news/imports/${id(importId)}/confirmation`, { text_sha256: textSha256, confirm: true },
           readImportConfirmed),
    limits: () => get("/api/user/limits", readLimits),
    quality: (analysisId: string) => get(`/api/user/analyses/${id(analysisId)}/quality`, readQuality),
  };
}

export type NewsApi = ReturnType<typeof newsApi>;

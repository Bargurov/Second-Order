// Research views (/api/research and /api/research/:id): committed comparisons of selected retained publications, each
// statement tied to quoted passages that the server checks against the retained sources on every read. Replies are
// read fail-closed: counts must reconcile with the states they describe, a comparison may show its observation and
// evidence only when every publication it compares checked, and every quoted passage must cite a paragraph of a
// compared publication. Nothing here requests anything outside this server.
import type { Loaded } from "./api";
import { formatDay, formatUtc } from "./format.ts";

export const RESEARCH_VIEW_VERSION = "policy-research-view-0.1";
export const DIMENSIONS = ["instrument", "relation", "scope", "parties", "supply_chain", "timing", "conditions"] as const;
export const STATUSES = ["stated", "interpretation", "not_stated", "referenced_unread"] as const;
export const STAGES = ["design_software", "equipment", "fabrication", "memory", "chips", "computing_systems",
  "ai_models"] as const;
export const PUBLICATION_STATES = ["verified", "changed", "missing"] as const;
export const COMPARISON_STATES = ["available", "needs_revalidation", "unavailable"] as const;
const DATE_KINDS = ["effective", "compliance", "comment_deadline", "license_deadline", "issued", "conduct",
  "designation"];
const PRECISIONS = ["day", "year", "relative"];
const LISTING_FIELDS = ["published", "created", "changed"] as const;
const KEY = /^[0-9a-f]{20}$/;
const SHA = /^[0-9a-f]{64}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type Dimension = (typeof DIMENSIONS)[number];
export type Status = (typeof STATUSES)[number];
export type Stage = (typeof STAGES)[number];
export type PublicationState = (typeof PUBLICATION_STATES)[number];
export type ComparisonState = (typeof COMPARISON_STATES)[number];
export interface Excerpt { paragraph: number; quote: string }
export interface StatedDate { kind: string; value: string | null; precision: "day" | "year" | "relative";
  as_stated: string }
export interface Statement { status: Status; text: string; excerpts: Excerpt[]; reference: string | null;
  stage: Stage | null; dates: StatedDate[] }
export interface DimensionEntry { label: string; statements: Statement[] }
export interface Reference { id: string; description: string; excerpts: Excerpt[] }
export interface CaseLink { kind: "library" | "historical"; id: string; title: string; href: string; note: string }
export interface Publication {
  id: string; position: number; short_title: string; title: string; url: string; state: PublicationState;
  problems: string[]; record: { key: string; record_sha256: string; paragraphs: number };
  listing: { published: string; created: string | null; changed: string | null };
  dateline: { page: string; state: PublicationState; value: string | null; detail: string } | null;
  text: { status: "checked" | "listing_text"; detail: string }; why_included: string; cases: CaseLink[];
  dimensions: Record<Dimension, DimensionEntry> | null; stages: Stage[] | null; references: Reference[] | null;
}
export interface Evidence {
  publication: string; kind: "quote" | "field" | "absence"; paragraph: number | null; paragraphs: number;
  quote: string | null; field: (typeof LISTING_FIELDS)[number] | null; value: string | null; absent: string | null;
}
export interface Comparison {
  id: string; kind: string; question: string; publications: string[]; state: ComparisonState; problems: string[];
  observation: string | null; evidence: Evidence[] | null; why: string | null; unknown: string | null;
  would_establish: string | null;
}
export interface ReleasePage { id: string; url: string; approval_id: string; sha256: string; bytes: number;
  retrieved_at: string; dateline: string; state: PublicationState; detail: string }
export interface ResearchView {
  view_version: string; research_version: string; id: string; title: string; question: string; scope_note: string;
  corpus_notes: string[]; method_note: string; provider_called: false;
  labels: { statuses: Record<Status, string>; dimensions: Record<Dimension, string>; stages: Record<Stage, string>;
    date_kinds: Record<string, string>; precisions: Record<string, string>; comparison_kinds: Record<string, string>;
    listing_fields: Record<string, string>; publication_states: Record<PublicationState, string>;
    comparison_states: Record<ComparisonState, string> };
  snapshot: { approval_id: string; url: string; sha256: string; bytes: number; retrieved_at: string;
    extractor_version: string; state: PublicationState; detail: string; filter_matches: number | null };
  release_pages: ReleasePage[];
  counts: { publications: Record<PublicationState, number>; comparisons: Record<ComparisonState, number> };
  publications: Publication[]; comparisons: Comparison[];
  not_included: { title: string; url: string; listed: string; reason: string; state: PublicationState;
    case: CaseLink | null }[];
  not_claimed: string[];
  provenance: { prepared_by: string; prepared_on: string; method: string; ai_assisted: true;
    human_review: "not_reviewed"; research_use: "excluded" };
}

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
const iso = (value: unknown): value is string => isText(value) && !Number.isNaN(Date.parse(value));
const labelled = (value: unknown, keys: readonly string[]) => object(value) && keys.every((key) => isText(value[key]));

/** A press-release address on BIS's own site: the only publication links a research view may carry. */
export function pressReleaseLink(url: unknown): boolean {
  if (typeof url !== "string") return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "www.bis.gov" && !parsed.username && !parsed.port &&
      !parsed.search && !parsed.hash && /^\/press-release\/[a-z0-9][a-z0-9.-]*$/.test(parsed.pathname) &&
      url === `https://www.bis.gov${parsed.pathname}`;
  } catch {
    return false;
  }
}

const caseOk = (link: unknown): boolean => object(link) && (link.kind === "library" || link.kind === "historical") &&
  isText(link.id) && isText(link.title) && isText(link.note) &&
  link.href === (link.kind === "library" ? `/library/${link.id}` : `/library/historical/${link.id}`);

function excerptsOk(value: unknown, paragraphs: number, minimum: number): boolean {
  return Array.isArray(value) && value.length >= minimum && value.every((item) => object(item) &&
    Number.isInteger(item.paragraph) && (item.paragraph as number) >= 1 && (item.paragraph as number) <= paragraphs &&
    isText(item.quote));
}

function statementOk(statement: unknown, dimension: Dimension, paragraphs: number, references: Set<string>): boolean {
  if (!object(statement) || !STATUSES.includes(statement.status as Status) || !isText(statement.text) ||
      !Array.isArray(statement.dates)) return false;
  const status = statement.status as Status;
  if (!excerptsOk(statement.excerpts, paragraphs, status === "not_stated" ? 0 : 1)) return false;
  if (status === "not_stated" && (statement.excerpts as Excerpt[]).length > 0) return false;
  if ((status === "referenced_unread") !== (statement.reference !== null)) return false;
  if (status === "referenced_unread" && !references.has(statement.reference as string)) return false;
  const supply = dimension === "supply_chain";
  if (supply && !(status === "interpretation" ? STAGES.includes(statement.stage as Stage)
    : status === "not_stated" && statement.stage === null)) return false;
  if (!supply && statement.stage !== null) return false;
  if (statement.dates.length > 0 && !(dimension === "timing" && status === "stated")) return false;
  return (statement.dates as unknown[]).every((date) => object(date) && DATE_KINDS.includes(date.kind as string) &&
    PRECISIONS.includes(date.precision as string) && isText(date.as_stated) &&
    (date.precision === "relative" ? date.value === null : isText(date.value)));
}

function publicationOk(item: Publication, position: number): boolean {
  if (!object(item) || item.position !== position || !isText(item.id) || !isText(item.short_title) ||
      !isText(item.title) || !pressReleaseLink(item.url) || !PUBLICATION_STATES.includes(item.state) ||
      !texts(item.problems) || !object(item.record) || !KEY.test(item.record.key) ||
      !SHA.test(item.record.record_sha256) || !Number.isInteger(item.record.paragraphs) || item.record.paragraphs < 1 ||
      !object(item.listing) || !iso(item.listing.published) || !object(item.text) ||
      !["checked", "listing_text"].includes(item.text.status) || !isText(item.text.detail) ||
      !isText(item.why_included) || !Array.isArray(item.cases) || !item.cases.every(caseOk)) return false;
  if (item.dateline !== null && !(object(item.dateline) && PUBLICATION_STATES.includes(item.dateline.state) &&
      (item.dateline.state === "verified" ? isText(item.dateline.value) : item.dateline.value === null))) return false;
  if (item.text.status === "checked" && !(item.state === "verified" && item.dateline?.state === "verified")) return false;
  if (item.state !== "verified") {
    return item.problems.length > 0 && item.dimensions === null && item.stages === null && item.references === null;
  }
  if (item.problems.length > 0 || !object(item.dimensions) || !Array.isArray(item.references) ||
      !Array.isArray(item.stages)) return false;
  const references = new Set(item.references.map((reference) => reference.id));
  if (!item.references.every((reference) => object(reference) && isText(reference.description) &&
      excerptsOk(reference.excerpts, item.record.paragraphs, 1))) return false;
  const dimensions = item.dimensions as Record<string, unknown>;
  if (Object.keys(dimensions).length !== DIMENSIONS.length) return false;
  for (const name of DIMENSIONS) {
    const entry = dimensions[name];
    if (!object(entry) || !isText(entry.label) || !Array.isArray(entry.statements) || entry.statements.length === 0 ||
        !entry.statements.every((statement) => statementOk(statement, name, item.record.paragraphs, references))) {
      return false;
    }
  }
  const stages = item.dimensions.supply_chain.statements.flatMap((statement) => statement.stage ? [statement.stage] : []);
  return stages.length === item.stages.length && stages.every((stage, index) => stage === item.stages![index]);
}

function comparisonOk(comparison: Comparison, states: Map<string, PublicationState>,
                      paragraphs: Map<string, number>): boolean {
  if (!object(comparison) || !isText(comparison.id) || !isText(comparison.question) || !isText(comparison.kind) ||
      !texts(comparison.publications) || comparison.publications.length < 2 ||
      new Set(comparison.publications).size !== comparison.publications.length ||
      !comparison.publications.every((id) => states.has(id)) || !COMPARISON_STATES.includes(comparison.state) ||
      !texts(comparison.problems)) return false;
  const compared = comparison.publications.map((id) => states.get(id));
  const content = [comparison.observation, comparison.why, comparison.unknown, comparison.would_establish];
  if (comparison.state !== "available") {
    const fits = comparison.state === "unavailable" ? compared.includes("missing")
      : !compared.includes("missing");
    return fits && comparison.problems.length > 0 && comparison.evidence === null && content.every((x) => x === null);
  }
  if (!compared.every((state) => state === "verified") || comparison.problems.length > 0 || !content.every(isText) ||
      !Array.isArray(comparison.evidence) || comparison.evidence.length < 2) return false;
  const cited = new Set<string>();
  for (const evidence of comparison.evidence) {
    if (!object(evidence) || !comparison.publications.includes(evidence.publication) ||
        evidence.paragraphs !== paragraphs.get(evidence.publication)) return false;
    const fine = evidence.kind === "quote"
      ? isText(evidence.quote) && Number.isInteger(evidence.paragraph) && (evidence.paragraph as number) >= 1 &&
        (evidence.paragraph as number) <= evidence.paragraphs && evidence.field === null && evidence.absent === null
      : evidence.kind === "field"
        ? LISTING_FIELDS.includes(evidence.field as never) && iso(evidence.value) && evidence.quote === null
        : evidence.kind === "absence" && isText(evidence.absent) && evidence.quote === null && evidence.field === null;
    if (!fine) return false;
    cited.add(evidence.publication);
  }
  return cited.size === comparison.publications.length;
}

/** The reply as served, or false: states, counts, citations and chronology must hold together. */
export function isResearchView(body: unknown, id: string): body is ResearchView {
  if (!object(body) || body.view_version !== RESEARCH_VIEW_VERSION || body.provider_called !== false ||
      body.id !== id || !isText(body.title) || !isText(body.question) || !isText(body.scope_note) ||
      !texts(body.corpus_notes) || !isText(body.method_note) || !object(body.labels) || !object(body.snapshot) ||
      !Array.isArray(body.publications) || !Array.isArray(body.comparisons) || !Array.isArray(body.not_included) ||
      !texts(body.not_claimed) || !object(body.counts) || !object(body.provenance) ||
      !Array.isArray(body.release_pages)) return false;
  const labels = body.labels as Record<string, unknown>;
  if (!labelled(labels.statuses, STATUSES) || !labelled(labels.dimensions, DIMENSIONS) ||
      !labelled(labels.stages, STAGES) || !labelled(labels.date_kinds, DATE_KINDS) ||
      !labelled(labels.precisions, PRECISIONS) || !labelled(labels.publication_states, PUBLICATION_STATES) ||
      !labelled(labels.comparison_states, COMPARISON_STATES) || !labelled(labels.listing_fields, LISTING_FIELDS) ||
      !object(labels.comparison_kinds)) return false;
  const snapshot = body.snapshot as ResearchView["snapshot"];
  if (!PUBLICATION_STATES.includes(snapshot.state) || !SHA.test(snapshot.sha256) || !isText(snapshot.detail) ||
      (snapshot.state === "verified" ? !count(snapshot.filter_matches) : snapshot.filter_matches !== null)) return false;
  const provenance = body.provenance as Record<string, unknown>;
  if (provenance.ai_assisted !== true || provenance.human_review !== "not_reviewed" ||
      provenance.research_use !== "excluded") return false;
  const publications = body.publications as Publication[];
  if (!publications.every((item, index) => publicationOk(item, index + 1)) ||
      new Set(publications.map((item) => item.id)).size !== publications.length) return false;
  if (snapshot.state !== "verified" && publications.some((item) => item.state !== snapshot.state)) return false;
  const times = publications.map((item) => Date.parse(item.listing.published));
  if (times.some((time, index) => index > 0 && time < times[index - 1])) return false;
  const states = new Map(publications.map((item) => [item.id, item.state]));
  const paragraphs = new Map(publications.map((item) => [item.id, item.record.paragraphs]));
  const comparisons = body.comparisons as Comparison[];
  if (!comparisons.every((comparison) => comparisonOk(comparison, states, paragraphs)) ||
      new Set(comparisons.map((comparison) => comparison.id)).size !== comparisons.length) return false;
  if (!(body.release_pages as ReleasePage[]).every((page) => object(page) && PUBLICATION_STATES.includes(page.state) &&
      SHA.test(page.sha256) && isText(page.dateline))) return false;
  if (!(body.not_included as ResearchView["not_included"]).every((item) => object(item) && isText(item.title) &&
      pressReleaseLink(item.url) && iso(item.listed) && isText(item.reason) &&
      PUBLICATION_STATES.includes(item.state) && (item.case === null || caseOk(item.case)))) return false;
  const counts = body.counts as ResearchView["counts"];
  return object(counts.publications) && object(counts.comparisons) &&
    PUBLICATION_STATES.every((state) => counts.publications[state] ===
      publications.filter((item) => item.state === state).length) &&
    COMPARISON_STATES.every((state) => counts.comparisons[state] ===
      comparisons.filter((item) => item.state === state).length);
}

async function read<T>(path: string, signal: AbortSignal, check: (body: unknown) => body is T): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = object(body) && typeof body.detail === "string" ? body.detail
    : `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  return check(body) ? { state: "ready", data: body } : { state: "error", message: "The reply could not be read by this page." };
}

export const fetchResearch = (id: string, signal: AbortSignal) =>
  read(`/api/research/${encodeURIComponent(id)}`, signal, (body): body is ResearchView => isResearchView(body, id));

// ---------------------------------------------------------------- reading aids

/** "13 Jan 2026, 23:00 UTC": a listing time exactly as stored, in UTC. */
export const listingTime = (value: string) => formatUtc(value);
/** "13 Jan 2026": the UTC day of a listing time. */
export const listingDay = (value: string) => formatDay(value);

/** A stated date in its own precision: a day, a year, or the stated relative wording. */
export function statedDate(date: StatedDate): string {
  if (date.precision === "day" && date.value) return formatDay(`${date.value}T00:00:00Z`);
  if (date.precision === "year" && date.value) return date.value;
  return `“${date.as_stated}”`;
}

/** Every date a publication's text states. */
export function statedDates(item: Publication): StatedDate[] {
  return item.dimensions ? item.dimensions.timing.statements.flatMap((statement) => statement.dates) : [];
}

/** The timing statements that state dates, so each date can be shown with what it is the date of. */
export function datedStatements(item: Publication): Statement[] {
  return item.dimensions ? item.dimensions.timing.statements.filter((statement) => statement.dates.length > 0) : [];
}

/** A supply-chain statement's stage label, unless the statement already says it in the same words. */
export const stageNote = (statement: Statement, label: string): string | null =>
  statement.text.toLowerCase().startsWith(label.toLowerCase()) ? null : label;

/** Each stage, with the publications whose text names an item at it (the curator's reading). */
export function stageColumns(view: ResearchView): { stage: Stage; label: string; named: Set<string> }[] {
  return STAGES.map((stage) => ({
    stage, label: view.labels.stages[stage],
    named: new Set(view.publications.filter((item) => item.stages?.includes(stage)).map((item) => item.id)),
  }));
}

export const STATUS_MARK: Record<Status, string> = {
  stated: "Publisher", interpretation: "Curator", not_stated: "Not stated", referenced_unread: "Not retained",
};

/** The distinct statuses of a dimension's statements, in a fixed order. */
export const statusesOf = (entry: DimensionEntry): Status[] =>
  STATUSES.filter((status) => entry.statements.some((statement) => statement.status === status));

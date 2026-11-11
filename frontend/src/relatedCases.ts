// Related Cases: the committed historical cases (/api/related-cases) and one event's stored match
// (/api/related-cases/events/:kind/:id). The server words every explanation; this module refuses replies whose
// identities, citations or counts do not hold together, or that would show a match the rule does not allow, and it
// never repeats the matching.
import type { Loaded } from "./api";
import { formatDay } from "./library.ts";

export const RELATED_VIEW_VERSION = "related-cases-view-0.1";
export const MATCH_VIEW_VERSION = "related-match-view-0.1";
export const RELATED_HEADER = "X-Second-Order-Related";
export const DIMENSIONS = ["instrument", "sector", "geography", "agency"] as const;
export type Dimension = (typeof DIMENSIONS)[number];
export const DATE_KINDS = ["announcement", "action", "effective", "publication", "deadline"] as const;
const CHECK_STATES = ["verified", "absent", "different"] as const;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const SHA = /^[a-f0-9]{64}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export interface RelatedRow {
  id: string; title: string; topic: string; summary: string; announced: string; date_as_stated: string;
  publisher: string;
}
export interface Unfinished { topic: string; planned_source: string; outcome: string }
interface Header {
  view_version: string; collection_version: string; title: string; introduction: string; labels: string[];
  historical_note: string; coverage_note: string; matching_note: string; unfinished: Unfinished[];
}
export interface RelatedCollection extends Header { cases: RelatedRow[] }

export interface Fact { id: string; text: string; quotes: string[] }
export interface DateItem {
  kind: (typeof DATE_KINDS)[number]; label: string; date: string | null; as_stated: string | null; facts: string[];
  note: string | null;
}
export interface Cited { facts: string[] }
export interface RelatedCase {
  collection_version: string; id: string; title: string; topic: string; summary: { text: string } & Cited;
  source: {
    publisher: string; title: string; url: string; kind: string; date_as_stated: string;
    retained: { approval_id: string; attempt: number; folder: string; file: string; sha256: string; bytes: number;
      media_type: string; requested_at: string; received_at: string };
  };
  dates: DateItem[]; facts: Fact[];
  scope: ({ text: string } & Cited)[];
  actors: ({ name: string; role: string } & Cited)[];
  tags: Record<Dimension, ({ slug: string } & Cited)[]>;
  comparison_points: ({ label: string; case_value: string } & Cited)[];
  interpretation: { channels: ({ title: string; text: string } & Cited)[]; why_read: string };
  unknowns: string[];
  provenance: { prepared_by: string; prepared_on: string; method: string; sources_read: string[]; ai_assisted: true;
    human_review: "not_reviewed"; research_use: "excluded"; currency: "historical" };
}
export interface SourceCheck {
  state: (typeof CHECK_STATES)[number]; acquisition_record: "matches" | "absent" | "differs"; detail: string;
  sha256: string; bytes: number; quotes: number;
}
export interface RelatedCaseView extends Header {
  case: RelatedCase; announced: string; position: number; count: number;
  previous: { id: string; title: string } | null; next: { id: string; title: string } | null;
  source_check: SourceCheck; interpretation_label: string; facts_note: string; date_kinds: Record<string, string>;
  dimension_labels: Record<Dimension, string>; tag_labels: Record<Dimension, Record<string, string>>;
  rules_version: string; provider_called: false;
}

export interface Found { term: string; field: string; hint: boolean }
export interface SharedItem { dimension: Dimension; value: string; label: string; found: Found[]; text: string }
export interface DiffItem { dimension: Dimension; kind: "different" | "also_names"; event: string[]; case: string[];
  text: string }
export interface UnknownItem { dimension: Dimension; case: string[]; text: string }
export interface RelatedMatch {
  case_id: string; title: string; topic: string; announced: string; date_as_stated: string; publisher: string;
  shared_dimensions: number; shared: SharedItem[]; differs: DiffItem[]; unknown: UnknownItem[]; timing: string;
  not_compared: { label: string; case_value: string }[]; why_read: string; rests_on_hint: boolean;
  hint_note: string | null;
}
export interface Overlap { case_id: string; title: string; missing: "instrument" | "sector_or_country";
  shared: Omit<SharedItem, "text">[]; text: string }
export interface Hint {
  entry_id: string; fingerprint: string; mode: "paid"; triage_id: string; config_key: string; current_config: boolean;
  received_at: string; category: string; event_type: string | null; summary: string; note: string;
}
export interface MatchEvent {
  title: string; publisher: string | null; source: string | null; link: string; date_label: string;
  date_short: string; date_value: string | null; held: string;
  identity: { kind: "inbox" | "capture"; id: string } & Record<string, string>;
  inputs: { field: string; label: string; present: boolean }[]; hint: Hint | null;
}
export interface MatchView {
  view_version: string; kind: "inbox" | "capture"; id: string; state: "not_checked" | "checked" | "problem";
  detail: string | null; event: MatchEvent; cases_available: number; coverage_note: string; matching_note: string;
  historical_note: string; not_compared_note: string; rules_version: string; kept_records: number | null;
  unreadable_records?: number; written: false; provider_called: false;
  match: null | {
    match_id: string; computed_at: string; rules_version: string; collection_version: string;
    related: RelatedMatch[]; overlaps: Overlap[];
    tags: Record<Dimension, Record<string, { label: string; found: Found[] }>>;
  };
}
export interface CheckOutcome { view_version: string; match_id: string; created: boolean; related: number;
  overlaps: number; provider_called: false }

const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const distinct = (values: string[]) => new Set(values).size === values.length;

function headerOk(body: Record<string, unknown>): boolean {
  return body.view_version === RELATED_VIEW_VERSION && body.collection_version === "related-cases-0.1" &&
    ["title", "introduction", "historical_note", "coverage_note", "matching_note"].every((key) => isText(body[key])) &&
    texts(body.labels) && Array.isArray(body.unfinished) &&
    body.unfinished.every((item) => object(item) && isText(item.topic) && isText(item.planned_source) &&
      isText(item.outcome));
}

/** The case library's list: distinct cases in announcement order, each with a calendar date. */
export function isRelatedCollection(body: unknown): body is RelatedCollection {
  if (!object(body) || !headerOk(body) || !Array.isArray(body.cases) || body.cases.length === 0) return false;
  const rows = body.cases as unknown[];
  if (!rows.every((row) => object(row) && ["id", "title", "topic", "summary", "date_as_stated", "publisher"]
    .every((key) => isText(row[key])) && typeof row.announced === "string" && formatDay(row.announced) !== null)) {
    return false;
  }
  const days = (rows as RelatedRow[]).map((row) => row.announced);
  return distinct((rows as RelatedRow[]).map((row) => row.id)) && days.every((day, i) => i === 0 || days[i - 1] <= day);
}

function citedOk(item: unknown, facts: Set<string>): boolean {
  return object(item) && texts(item.facts) && (item.facts as string[]).length > 0 &&
    distinct(item.facts as string[]) && (item.facts as string[]).every((id) => facts.has(id));
}

/** One case: every citation names a fact of the case, every fact has quotes, the dates are well formed, the review
 *  status is the one the page states, and the neighbours agree with the position. */
export function isRelatedCaseView(body: unknown): body is RelatedCaseView {
  if (!object(body) || !headerOk(body) || body.provider_called !== false || !object(body.case)) return false;
  const item = body.case as unknown as RelatedCase;
  if (!Array.isArray(item.facts) || !item.facts.every((fact) => object(fact) && isText(fact.id) && isText(fact.text) &&
      texts(fact.quotes) && fact.quotes.length > 0)) return false;
  const facts = new Set(item.facts.map((fact) => fact.id));
  if (facts.size !== item.facts.length) return false;
  const cited = [item.summary, ...(item.dates ?? []), ...(item.scope ?? []), ...(item.actors ?? []),
                 ...(item.comparison_points ?? []), ...(item.interpretation?.channels ?? []),
                 ...DIMENSIONS.flatMap((dimension) => item.tags?.[dimension] ?? [])];
  if (!cited.every((entry) => citedOk(entry, facts))) return false;
  if (!Array.isArray(item.dates) || !item.dates.every((date) => DATE_KINDS.includes(date.kind) && isText(date.label) &&
      (date.date === null ? isText(date.note) : DAY.test(date.date) && isText(date.as_stated)))) return false;
  const announced = item.dates.filter((date) => date.kind === "announcement");
  if (announced.length !== 1 || announced[0].date !== body.announced) return false;
  const provenance = item.provenance;
  if (!object(provenance) || provenance.human_review !== "not_reviewed" || provenance.currency !== "historical" ||
      provenance.ai_assisted !== true || provenance.research_use !== "excluded") return false;
  const check = body.source_check as SourceCheck | undefined;
  if (!object(check) || !CHECK_STATES.includes(check.state) || !isText(check.detail) ||
      check.sha256 !== item.source?.retained?.sha256) return false;
  const position = body.position, count = body.count;
  if (typeof position !== "number" || typeof count !== "number" || position < 1 || position > count) return false;
  return (body.previous === null) === (position === 1) && (body.next === null) === (position === count) &&
    isText(item.interpretation.why_read) && texts(item.unknowns) && isText(body.interpretation_label);
}

function sharedOk(item: unknown): boolean {
  return object(item) && (DIMENSIONS as readonly unknown[]).includes(item.dimension) && isText(item.value) &&
    isText(item.label) && Array.isArray(item.found) && item.found.length > 0 &&
    item.found.every((found) => object(found) && isText(found.term) && isText(found.field) &&
      typeof found.hint === "boolean");
}

/** One event's match: a related case must share its instrument and its sector or country (the rule); shared
 *  dimensions are counted from what is listed; hint terms and the hint note require a saved hint; an overlap's
 *  missing part agrees with what it shares; no case is both related and an overlap. */
export function isMatchView(body: unknown): body is MatchView {
  if (!object(body) || body.view_version !== MATCH_VIEW_VERSION || body.written !== false ||
      body.provider_called !== false || !["inbox", "capture"].includes(body.kind as string) || !isText(body.id) ||
      !["not_checked", "checked", "problem"].includes(body.state as string) || !object(body.event)) return false;
  const event = body.event as unknown as MatchEvent;
  if (!object(event.identity) || event.identity.kind !== body.kind || event.identity.id !== body.id ||
      !isText(event.title) || !Array.isArray(event.inputs) ||
      !event.inputs.every((input) => object(input) && isText(input.field) && isText(input.label) &&
        typeof input.present === "boolean")) return false;
  if (event.hint !== null && !(object(event.hint) && event.hint.mode === "paid" && isText(event.hint.note))) return false;
  if (body.state !== "checked") return body.match === null;
  const match = body.match as MatchView["match"];
  if (!object(match) || !SHA.test(match.match_id) || !Array.isArray(match.related) || !Array.isArray(match.overlaps)) {
    return false;
  }
  const hinted = (found: Found[]) => found.some((item) => item.hint);
  for (const row of match.related) {
    if (!object(row) || !isText(row.case_id) || !Array.isArray(row.shared) || !row.shared.every(sharedOk) ||
        !isText(row.timing) || !isText(row.why_read) || !Array.isArray(row.differs) || !Array.isArray(row.unknown)) {
      return false;
    }
    const dimensions = new Set(row.shared.map((item) => item.dimension));
    if (!dimensions.has("instrument") || !(dimensions.has("sector") || dimensions.has("geography"))) return false;
    if (row.shared_dimensions !== dimensions.size) return false;
    if (row.rests_on_hint !== (row.hint_note !== null)) return false;
    if ((row.rests_on_hint || row.shared.some((item) => hinted(item.found))) && event.hint === null) return false;
  }
  for (const row of match.overlaps) {
    if (!object(row) || !isText(row.case_id) || !Array.isArray(row.shared) || !row.shared.every(sharedOk) ||
        !isText(row.text)) return false;
    const dimensions = new Set(row.shared.map((item) => item.dimension));
    const instrument = dimensions.has("instrument");
    const qualifies = dimensions.has("sector") || dimensions.has("geography");
    if (row.missing === "instrument" ? instrument || !qualifies : !(row.missing === "sector_or_country" && instrument &&
        !qualifies)) return false;
  }
  const ids = [...match.related, ...match.overlaps].map((row) => row.case_id);
  return distinct(ids);
}

async function read<T>(path: string, signal: AbortSignal, valid: (body: unknown) => body is T): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = (object(body) && typeof body.detail === "string" ? body.detail : null) ??
    `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (response.status === 503) return { state: "not-prepared", message };
  if (!response.ok) return { state: "error", message };
  if (!valid(body)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body };
}

export const fetchRelatedCollection = (signal: AbortSignal) =>
  read("/api/related-cases", signal, isRelatedCollection);
export const fetchRelatedCase = (id: string, signal: AbortSignal) =>
  read(`/api/related-cases/${encodeURIComponent(id)}`, signal, isRelatedCaseView);
export const fetchRelatedMatch = (kind: string, id: string, signal: AbortSignal) =>
  read(`/api/related-cases/events/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, signal, isMatchView);

export type FindResult =
  | { state: "done"; data: CheckOutcome }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string };

/** The explicit local check. A missing reply is "unconfirmed"; nothing is sent again. */
export async function findRelatedCases(kind: string, id: string): Promise<FindResult> {
  let response: Response;
  try {
    response = await fetch(`/api/related-cases/events/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/matches`, {
      method: "POST", body: JSON.stringify({ find_related_cases: true }),
      headers: { "Content-Type": "application/json", Accept: "application/json", [RELATED_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Reload the page to see whether "
      + "the result was saved; nothing was sent again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  const detail = object(payload) && typeof payload.detail === "string" ? payload.detail : null;
  if (response.status >= 500) return { state: "unconfirmed", message: detail ?? "The server failed." };
  if (!response.ok) return { state: "refused", message: detail ?? `Refused (${response.status}).` };
  const value = payload as CheckOutcome | null;
  if (!value || value.view_version !== MATCH_VIEW_VERSION || !SHA.test(value.match_id) ||
      value.provider_called !== false) {
    return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  }
  return { state: "done", data: value };
}

export const relatedCaseHref = (id: string) => `/library/historical/${encodeURIComponent(id)}`;

/** "7 October 2022", or the stated text when a date is not a calendar date. */
export const dayLabel = (day: string) => formatDay(day) ?? day;

export const SOURCE_CHECK_LABEL: Record<SourceCheck["state"], string> = {
  verified: "Checked on this machine against the retained copy",
  absent: "Retained copy not on this machine",
  different: "The file on this machine is not the recorded copy",
};

/** Facts by ID, for showing what an item cites. */
export function factIndex(item: RelatedCase): Map<string, Fact> {
  return new Map(item.facts.map((fact) => [fact.id, fact]));
}

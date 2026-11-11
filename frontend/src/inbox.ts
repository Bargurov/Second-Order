// Event Inbox client: the cached inbox read with a GET, the explicit refresh POST, local filters by topic and source,
// and what an entry offers the Analyze an event form. Feed text arrives as plain text and is rendered as text, never
// as HTML. Publication information is the feed's own timestamp: shown raw with the element it came from, and offered
// as a date, time and offset only when the server found it unambiguous. Nothing here reads a time through the
// browser's time zone.
import type { Loaded } from "./api.ts";
import type { IntakeFields } from "./intake.ts";
import { SNAPSHOT_SOURCE, pressReleaseLink, type SnapshotRecord } from "./snapshot.ts";

export const INBOX_VIEW_VERSION = "event-inbox-view-0.1";

export interface FeedTimestamp {
  raw: string | null;
  origin: string;
  instant_utc: string | null;
  suggestion: { date: string; time: string; offset: string; dropped_fraction: string | null } | null;
  problem: string | null;
}

export interface InboxItem {
  id: string;
  /** The entry's place in its feed; null for a retained entry, which is no longer in the feed. */
  position: number | null;
  title: string;
  title_truncated: boolean;
  link: string;
  excerpt: string | null;
  excerpt_truncated: boolean;
  excerpt_repeats_title: boolean;
  feed_timestamp: FeedTimestamp;
  first_seen_at: string;
  source: string;
  publisher: string;
  /** The source's topic. */
  category: string;
  /** What the source lists: a statistical release, a policy announcement, an analysis article or a news announcement. */
  kind: string;
  /** The credit the publisher's reuse terms ask for; empty when none was checked. */
  attribution: string;
  /** When the source's last successful refresh retrieved this entry. */
  retrieved_at: string;
  /** The identity of this entry version's content (title, link, excerpt, feed timestamp): what a capture origin names. */
  content_sha256: string;
  /** True when the source's latest attempt failed or was not made: the entry comes from an earlier retrieval. */
  stale: boolean;
  /** Retained history: kept in the local archive after leaving its feed; retrieved_at is when it was last seen. */
  history?: true;
  last_seen_at?: string;
  versions?: number;
  /** Only on an entry imported from a retained snapshot: where it came from, and the record as extracted. */
  imported?: ImportedProvenance;
  /** Which texts the feed supplied for this entry and whether this inbox shortened them (feed entries only). */
  text?: EntryText;
}

/** The headline and the feed's excerpt (its own description, never the article): as supplied, or shortened here. */
export interface EntryText {
  title: "as_supplied" | "shortened";
  excerpt: "none" | "repeats_title" | "as_supplied" | "shortened";
}

/** One recorded feed request, as the server summarises its retrieval record. */
export interface AcquisitionSummary {
  number: number;
  started_at: string;
  finished_at: string | null;
  outcome: "accepted" | "refused" | "failed";
  detail: string | null;
  endpoint: string;
  http_status: number | null;
  headers: Record<string, string>;
  validators: { etag: string | null; last_modified: string | null } | null;
  body: { state: "complete" | "partial" | "not_read" | "none"; bytes: number; sha256: string | null;
          declared_bytes: number | null; content_encoding: string | null; kept: string | null };
  /** The privately kept response checked against its record: verified, missing or differs; null when none was kept. */
  kept_copy: "verified" | "missing" | "differs" | null;
  parser_version: string | null;
  /** How the accepted response's entries compared with what was held before; null when it was not accepted. */
  counts: { new: number; changed: number; unchanged: number; no_longer_listed: number; skipped: number;
            duplicates: number; not_retained: number; basis: string | null } | null;
  notes: string[];
}

export interface ImportedProvenance {
  label: string;
  import_id: string;
  imported_at: string;
  version: number;
  versions: number;
  record_sha256: string;
  completeness: string;
  snapshot: { package: { url: string; sha256: string; bytes: number; retrieved_at: string; approval_id: string };
              extractor_version: string; index_version: string; index_sha256: string };
  record: SnapshotRecord;
}

export type SourceState = "never_refreshed" | "ok" | "failed" | "not_requested" | "unreadable";

export interface InboxSource {
  key: string;
  label: string;
  publisher: string;
  category: string;
  kind: string;
  attribution: string;
  feed_url: string;
  catalogue_url: string;
  terms_url: string;
  policy_url: string | null;
  contact_required: boolean;
  state: SourceState;
  problem: string | null;
  last_attempt: { started_at: string; finished_at: string | null; outcome: string; detail: string | null;
                  http_status: number | null } | null;
  last_success: { retrieved_at: string; http_status: number; format: string; listed: number; not_retained: number;
                  duplicates: number; skipped_count: number; item_count: number } | null;
  /** The source's local archive of earlier entries and versions. */
  archive?: { state: "missing" | "ok" | "unreadable"; problem: string | null; entries: number; versions: number;
              retained: number };
  /** Whether this feed's entries also carry a full-article element (never read; kept in the retained response). */
  full_text_element?: boolean;
  /** The source's recorded requests: how many, the newest readable one, and newer ones that cannot be read. */
  acquisitions?: { count: number; latest: AcquisitionSummary | null; unreadable_newer: string[] };
}

export interface InboxView {
  view_version: string;
  retention: { per_source: number; statement: string };
  sources: InboxSource[];
  items: InboxItem[];
  /** Entries the archive keeps that are no longer in their feed's latest retrieval. */
  retained?: InboxItem[];
  /** Records explicitly imported from a retained snapshot: listed apart, never among the feeds' entries. */
  imported?: InboxItem[];
  imports?: { source: string; label: string; entries: number; versions: number; statement: string;
              unreadable: { key: string; problem: string }[] };
  refreshed?: { source: string; outcome: string; detail: string | null; acquisition?: AcquisitionSummary | null }[];
}

/** The fixed sources, in the server's order, each with the one host its feed and entries live on. */
export const SOURCE_HOSTS: Readonly<Record<string, string>> = {
  "fed-monetary": "www.federalreserve.gov", "bls-empsit": "www.bls.gov", "bls-cpi": "www.bls.gov",
  "eia-todayinenergy": "www.eia.gov", "wto-news": "www.wto.org",
};
const OFFICIAL_HOSTS = new Set(Object.values(SOURCE_HOSTS));

function httpsOn(url: string, hosts: Set<string>): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && hosts.has(parsed.hostname) && !parsed.username && !parsed.port;
  } catch {
    return false;
  }
}

/** An https address on one of the publishers' own hosts; anything else is never used as a link or a source URL. */
export const officialLink = (url: string): boolean => httpsOn(url, OFFICIAL_HOSTS);

/** A view this client can show: the expected version, the five fixed sources in order, and items whose links are on
 * their own source's host. */
function verified(body: unknown): InboxView | null {
  const view = body as InboxView | null;
  if (view?.view_version !== INBOX_VIEW_VERSION || !Array.isArray(view.sources) || !Array.isArray(view.items) ||
      typeof view.retention?.per_source !== "number") return null;
  const keys = view.sources.map((source) => source?.key);
  if (keys.join("\n") !== Object.keys(SOURCE_HOSTS).join("\n") ||
      !view.sources.every((source) => typeof source.category === "string" && typeof source.kind === "string" &&
                                      typeof source.attribution === "string")) return null;
  const valid = (item: InboxItem) => typeof item.title === "string" && typeof item.link === "string" &&
    Object.hasOwn(SOURCE_HOSTS, item.source) && httpsOn(item.link, new Set([SOURCE_HOSTS[item.source]])) &&
    typeof item.category === "string" && typeof item.kind === "string" && typeof item.attribution === "string" &&
    !!item.feed_timestamp;
  if (!view.items.every(valid)) return null;
  if (view.retained !== undefined && (!Array.isArray(view.retained) || !view.retained.every((item) =>
      valid(item) && item.history === true && typeof item.last_seen_at === "string"))) return null;
  if (view.imported !== undefined && (!Array.isArray(view.imported) || !view.imported.every(importedOk))) return null;
  return view;
}

/** An imported snapshot entry: a press-release address on BIS's site and the record of where it came from. */
function importedOk(item: InboxItem): boolean {
  const imported = item?.imported;
  return item?.source === SNAPSHOT_SOURCE && typeof item.title === "string" && pressReleaseLink(item.link) &&
    item.position === null && !!item.feed_timestamp && item.feed_timestamp.suggestion === null &&
    !!imported && typeof imported.label === "string" && typeof imported.import_id === "string" &&
    Number.isInteger(imported.version) && Number.isInteger(imported.versions) && imported.version <= imported.versions &&
    /^[0-9a-f]{64}$/.test(imported.snapshot?.package?.sha256 ?? "") && imported.record?.identity === item.link &&
    Array.isArray(imported.record?.text?.paragraphs) && item.id === `${SNAPSHOT_SOURCE}:${imported.record.key}`;
}

/** The link an entry may use: a feed entry's official address, or an imported record's BIS press-release address. */
export const entryLink = (item: InboxItem): boolean =>
  officialLink(item.link) || (item.source === SNAPSHOT_SOURCE && !!item.imported && pressReleaseLink(item.link));

function problem(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" ? detail : `Unexpected response (${status}).`;
}

/** The cached inbox as it is. The server reads its local cache only: no feed is requested by this. */
export async function fetchInbox(signal?: AbortSignal): Promise<Loaded<InboxView>> {
  let response: Response;
  try {
    response = await fetch("/api/inbox", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: "The local API did not answer. Start it with: python -m second_order serve" };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: "error", message: problem(body, response.status) };
  const view = verified(body);
  return view ? { state: "ready", data: view } : { state: "error", message: "The inbox could not be verified." };
}

export type RefreshResult = { state: "done"; view: InboxView } | { state: "failed" | "unconfirmed"; message: string };

/** The one explicit refresh: each listed feed requested once by the local server. It takes no options. */
export async function refreshInbox(): Promise<RefreshResult> {
  let response: Response;
  try {
    response = await fetch("/api/inbox/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Inbox": "1" },
      body: "{}",
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server; nothing was retried. Read the inbox again to see what it holds." };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: response.status >= 500 ? "unconfirmed" : "failed", message: problem(body, response.status) };
  const view = verified(body);
  return view ? { state: "done", view } : { state: "unconfirmed", message: "The refresh result could not be verified." };
}

/** Local filters over entries already held: "" means any. Filtering never requests or writes anything. */
export interface InboxFilter { topic: string; source: string }
export const NO_FILTER: InboxFilter = { topic: "", source: "" };

export const filtered = (items: InboxItem[], filter: InboxFilter): InboxItem[] =>
  items.filter((item) => (!filter.topic || item.category === filter.topic) && (!filter.source || item.source === filter.source));

/** The topics the sources cover, each once, in source order. */
export const topics = (sources: InboxSource[]): string[] => [...new Set(sources.map((source) => source.category))];

/** How an entry's kind is described: only BLS's formal releases are statistical releases. */
export function kindNote(kind: string): string {
  return kind === "Statistical release" ? "Formal statistical release" : `${kind}, not a statistical release`;
}

/** What an entry's official link leads to, by kind. */
export function linkLabel(kind: string): string {
  return kind === "Analysis article" ? "Official article" : kind === "News announcement" ? "Official news item"
    : "Official release";
}

/** "2026-10-08 09:00 UTC" from the server's UTC stamp, read from its own digits. */
export function utcStamp(stamp: string | null): string {
  const match = stamp ? /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d{1,6})?)?\+00:00$/.exec(stamp) : null;
  return match ? `${match[1]} ${match[2]} UTC` : stamp ?? "unknown";
}

/** What a source's card says about its state; "live" is never claimed. */
export function sourceStatus(source: InboxSource): { label: string; tone: "ok" | "warn" | "none" } {
  switch (source.state) {
    case "ok":
      return { label: `Retrieved ${utcStamp(source.last_success?.retrieved_at ?? null)} · as of that refresh, not live`, tone: "ok" };
    case "failed":
      return { label: `Latest refresh failed${source.last_success ? "; showing its last successful retrieval" : ""}`, tone: "warn" };
    case "not_requested":
      return { label: "Not requested on the latest refresh", tone: "warn" };
    case "unreadable":
      return { label: "Local record unreadable; not shown and not refreshed", tone: "warn" };
    default:
      return { label: "Never refreshed", tone: "none" };
  }
}

/** The form fields a suggestion would fill, exactly as the feed stated them; null when there is no suggestion. */
export function suggestedFields(timestamp: FeedTimestamp):
    Pick<IntakeFields, "publishedDate" | "publishedTime" | "publishedOffset"> | null {
  const suggestion = timestamp.suggestion;
  return suggestion ? { publishedDate: suggestion.date, publishedTime: suggestion.time, publishedOffset: suggestion.offset }
    : null;
}

/** The form an inbox entry starts: its headline and official link only. Time and published text stay empty. */
export function prefilledFields(item: InboxItem, empty: IntakeFields): IntakeFields {
  return { ...empty, headline: item.title, sourceUrl: entryLink(item) ? item.link : "" };
}

/** Whether the form differs from what was last filled in for the operator (by an inbox entry, or empty). */
export const edited = (fields: IntakeFields, baseline: IntakeFields) =>
  (Object.keys(fields) as (keyof IntakeFields)[]).some((key) => fields[key] !== baseline[key]);

const count = (n: number) => n.toLocaleString("en-US");

/** What a retrieval's entries were, compared with what was held before it: new, unchanged, changed, refused. */
export function countsLine(counts: NonNullable<AcquisitionSummary["counts"]>): string {
  const refused = [counts.skipped ? `${count(counts.skipped)} skipped` : "",
                   counts.duplicates ? `${count(counts.duplicates)} repeated` : ""].filter(Boolean);
  return `${count(counts.new)} new, ${count(counts.unchanged)} unchanged, ${count(counts.changed)} changed` +
    (refused.length ? `; refused: ${refused.join(", ")}` : "") +
    (counts.not_retained ? `; ${count(counts.not_retained)} beyond the entries kept` : "") +
    (counts.no_longer_listed ? `; ${count(counts.no_longer_listed)} no longer listed` : "");
}

const KEPT: Record<string, string> = {
  verified: "kept privately", missing: "its kept copy is missing",
  differs: "its kept copy no longer matches its record",
};

/** One recorded request in words: when, the status, the body and its SHA-256, the kept copy, the validators and the
 * parser. A retrieval is never called live, and its time is not a publication time. */
export function retrievalLine(summary: AcquisitionSummary): string {
  const when = `Request ${summary.number}, ${utcStamp(summary.started_at)}`;
  const status = summary.http_status === null ? "no response" : `HTTP ${summary.http_status}`;
  const body = summary.body;
  const encoding = body.content_encoding && body.content_encoding !== "identity"
    ? ` after undoing the server's ${body.content_encoding} encoding` : "";
  const hash = body.sha256 ? ` (SHA-256 ${body.sha256.slice(0, 12)}…)` : "";
  if (summary.outcome === "failed") {
    const arrived = body.state === "partial" ? `; ${count(body.bytes)} bytes arrived before it stopped${hash}` : "";
    return `${when}: ${status}, not retrieved${arrived}. ${summary.detail ?? ""}`.trim();
  }
  const received = `body received complete, ${count(body.bytes)} bytes${encoding}${hash}`;
  if (summary.outcome === "refused") return `${when}: ${status}, ${received}, not accepted. ${summary.detail ?? ""}`.trim();
  const validators = summary.validators && (summary.validators.etag || summary.validators.last_modified)
    ? `Cache validators: ${[summary.validators.etag ? `ETag ${summary.validators.etag}` : "",
                            summary.validators.last_modified ? `Last-Modified ${summary.validators.last_modified}` : ""]
        .filter(Boolean).join(", ")}.`
    : "The response gave no cache validators.";
  return `${when}: ${status}, ${received}${summary.kept_copy ? `, ${KEPT[summary.kept_copy]}` : ", not kept"}. ` +
    `${validators} Parsed by ${summary.parser_version}.`;
}

/** What one refresh did, one line per source, from the server's reply. */
export function refreshLines(rows: NonNullable<InboxView["refreshed"]>, sources: InboxSource[]): string[] {
  const label = (key: string) => sources.find((source) => source.key === key)?.label ?? key;
  return rows.map((row) => {
    const counts = row.acquisition?.counts;
    if (row.outcome === "ok") return `${label(row.source)}: ${counts ? countsLine(counts) : "refreshed (no retrieval record)"}.`;
    if (row.outcome === "not_requested") return `${label(row.source)}: not requested.`;
    if (row.outcome === "skipped_unreadable") return `${label(row.source)}: not refreshed; its local record is unreadable.`;
    const status = row.acquisition?.http_status;
    return `${label(row.source)}: did not refresh${status ? ` (HTTP ${status})` : ""}; its earlier entries are kept.`;
  });
}

const TITLE_TEXT: Record<EntryText["title"], string> = {
  as_supplied: "the headline as the feed supplies it", shortened: "the headline, shortened here at 300 characters",
};
const EXCERPT_TEXT: Record<EntryText["excerpt"], string> = {
  none: "no excerpt (the feed gives none)", repeats_title: "no excerpt (the feed's description repeats the headline)",
  as_supplied: "the feed's excerpt as supplied", shortened: "the feed's excerpt, shortened here at 1,200 characters",
};

/** Which texts an entry holds: the headline and the feed's own excerpt, never the article, which is not retrieved. */
export function textLine(text: EntryText | undefined, fullTextElement: boolean): string {
  if (!text) return "Held text: not stated for this entry.";
  return `Held text: ${TITLE_TEXT[text.title]}; ${EXCERPT_TEXT[text.excerpt]}. An excerpt is not the article, and the ` +
    "article was not retrieved." + (fullTextElement ? " This feed's responses also carry a full-article element, which " +
    "is never read or shown." : "");
}

// ---------------------------------------------------------------- processing at a glance

export const PROCESSING_INDEX_VERSION = "event-processing-index-0.1";

export interface ProcessingRow {
  model_triage: boolean;
  simulated_triage: boolean;
  triage_attention: boolean;
  triage_requests: number;
  captures: number;
}

export interface ProcessingIndex {
  index_version: string;
  provider_called: false;
  items: Record<string, ProcessingRow>;
  unreadable_triage_requests: number;
  unverified_links: number;
}

/** Per entry, which saved processing exists, from local records only; the event overview has the detail. */
export async function fetchProcessing(signal?: AbortSignal): Promise<Loaded<ProcessingIndex>> {
  let response: Response;
  try {
    response = await fetch("/api/events/processing", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: "The local API did not answer." };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: "error", message: problem(body, response.status) };
  const index = body as ProcessingIndex | null;
  return index?.index_version === PROCESSING_INDEX_VERSION && index.provider_called === false &&
    typeof index.items === "object" && index.items !== null
    ? { state: "ready", data: index } : { state: "error", message: "The processing index could not be verified." };
}

/** An entry's processing in a few words. "Not processed" is a state, not a failure. */
export function processingLabel(row: ProcessingRow | undefined): { label: string; tone: "none" | "done" | "warn" } {
  if (!row || (!row.model_triage && !row.simulated_triage && !row.triage_attention && !row.captures &&
               !row.triage_requests)) return { label: "Not processed", tone: "none" };
  const parts = [row.model_triage ? "Model triage saved" : row.simulated_triage ? "Simulated triage only" : "",
                 row.triage_attention ? "Triage failed or uncertain" : "",
                 !row.model_triage && !row.simulated_triage && !row.triage_attention && row.triage_requests
                   ? "Triage prepared, not sent" : "",
                 row.captures ? `${row.captures} saved ${row.captures === 1 ? "event" : "events"}` : ""].filter(Boolean);
  return { label: parts.join(" · "), tone: row.triage_attention ? "warn"
    : row.model_triage || row.simulated_triage || row.captures ? "done" : "none" };
}

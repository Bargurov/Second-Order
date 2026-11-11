// The retained BIS snapshot: BIS's News & Updates page, retained once on approval, browsed as local records and
// explicitly imported into the Event Inbox (/api/inbox/snapshots/bis). It is a snapshot, not a live feed: nothing here
// requests anything outside this server, and importing is local and free. Replies are read fail-closed: counts must
// reconcile with the rows they describe, every row and record must be one of this snapshot's press-release addresses,
// and a preview or import must answer for exactly the records selected, in order.
import type { Loaded } from "./api";

export const SNAPSHOT_VIEW_VERSION = "bis-snapshot-view-0.1";
export const SNAPSHOT_SOURCE = "bis-snapshot";
export const SNAPSHOT_HOST = "www.bis.gov";
export const COMPLETENESS = ["checked", "checked_differs", "listing_text", "title_only", "unreadable"] as const;
export const FILTERS = ["semiconductors", "export_controls"] as const;
export const IMPORT_STATES = ["new", "imported", "changed", "unreadable"] as const;
export const PREVIEW_STATES = ["new", "existing", "changed", "unusable"] as const;
export const OUTCOMES = ["added", "version_added", "reused", "kept", "unusable", "conflict"] as const;
const DATE_STATES = ["listed", "missing", "ambiguous"];
const KEY = /^[0-9a-f]{20}$/;
const SHA = /^[0-9a-f]{64}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type Completeness = (typeof COMPLETENESS)[number];
export type FilterName = (typeof FILTERS)[number];
export interface SnapshotRow {
  key: string; id: string; title: string; link: string; position: number; date: string | null;
  date_state: "listed" | "missing" | "ambiguous"; published: string | null; topics: string[];
  external_host: string | null; completeness: Completeness; text_chars: number; opening: string;
  filters: Record<FilterName, boolean>; same_title: number;
  import: { state: (typeof IMPORT_STATES)[number]; versions: number | null };
}
export interface Package { url: string; approval_id: string; attempt: number; sha256: string; bytes: number;
  retrieved_at: string; content_type: string }
export interface SnapshotView {
  view_version: string; state: "unavailable" | "refused" | "not_opened" | "open"; label: string; page_url: string;
  statement: string; filters_note: string; filters: Record<FilterName, string>;
  completeness_labels: Record<Completeness, string>; selection_limit: number; provider_called: false;
  problem: string | null; package: Package | null;
  index: { name: string; version: string; extractor_version: string; built_at: string; content_sha256: string;
    release_pages: { url: string; attempt: number; sha256: string; verified: boolean }[] } | null;
  counts: {
    listed: number; usable: number; unusable: number; completeness: Record<Completeness, number>;
    dates: Record<"listed" | "missing" | "ambiguous", number>; date_range: [string, string] | null;
    external_links: number; external_hosts: Record<string, number>; topics: Record<string, number>;
    filters: Record<FilterName, number>; same_title_records: number; duplicate_copies: number;
  } | null;
  rows: SnapshotRow[]; unusable: { position: number; key: string | null; path: string | null; title: string | null;
    reasons: string[] }[];
  opened?: "built" | "reused";
}
export interface ListingTime { state: "listed" | "missing" | "ambiguous"; time: string | null; date: string | null;
  field: string; problem: string | null }
export interface SnapshotRecord {
  key: string; id: string; identity: string; position: number;
  document: { path: string; uuid: string | null; node_id: string | null };
  publisher: { title: string; title_truncated: boolean; topics: string[]; countries: string[]; summary: string | null;
    summary_truncated: boolean; external_link: { url: string; host: string; title: string | null } | null };
  text: { paragraphs: string[]; chars: number; truncated: boolean; state: string; problem: string | null };
  listing: { published: ListingTime; created: ListingTime; changed: ListingTime; sticky: boolean };
  filters: Record<FilterName, { matched: boolean; in: string[]; terms: string[] }>;
  same_title: { key: string; path: string; date: string | null; relation: string }[];
  check: { page_url: string; page_sha256: string; attempt: number; dateline: string | null; result: string;
    note: string | null } | null;
  completeness: Completeness; notes: string[]; record_sha256: string;
}
export interface RecordView { view_version: string; record: SnapshotRecord; package: Package; completeness: string;
  import: SnapshotRow["import"]; provider_called: false }
export interface PreviewRow { key: string; id: string; title: string | null; state: (typeof PREVIEW_STATES)[number];
  reasons: string[]; version?: number; changed?: string[] }
export interface Preview { rows: PreviewRow[]; counts: Record<(typeof PREVIEW_STATES)[number], number>; cost: string;
  writes: boolean }
export interface ImportRow extends PreviewRow { outcome: (typeof OUTCOMES)[number] }
export interface ImportResult { import_id: string | null; imported_at: string | null; rows: ImportRow[];
  counts: Record<(typeof OUTCOMES)[number], number>; written: boolean; cost: string }

const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

/** A press-release address on BIS's own site: the only links a snapshot record may carry. */
export function pressReleaseLink(url: unknown): boolean {
  if (typeof url !== "string") return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === SNAPSHOT_HOST && !parsed.username && !parsed.port &&
      !parsed.search && !parsed.hash && /^\/press-release\/[a-z0-9][a-z0-9.-]*$/.test(parsed.pathname) &&
      !parsed.pathname.includes("..") && url === `https://${SNAPSHOT_HOST}${parsed.pathname}`;
  } catch {
    return false;
  }
}

function rowOk(row: SnapshotRow): boolean {
  return object(row) && KEY.test(row.key) && row.id === `${SNAPSHOT_SOURCE}:${row.key}` && isText(row.title) &&
    pressReleaseLink(row.link) && Number.isInteger(row.position) && DATE_STATES.includes(row.date_state) &&
    (row.date_state === "listed" ? typeof row.date === "string" && DAY.test(row.date) : row.date === null) &&
    texts(row.topics) && (row.external_host === null || isText(row.external_host)) &&
    COMPLETENESS.includes(row.completeness) && count(row.text_chars) && typeof row.opening === "string" &&
    object(row.filters) && FILTERS.every((name) => typeof row.filters[name] === "boolean") && count(row.same_title) &&
    object(row.import) && IMPORT_STATES.includes(row.import.state);
}

/** The reply as served, or false; an open view's counts must equal what its own rows show. */
export function isSnapshotView(body: unknown): body is SnapshotView {
  if (!object(body) || body.view_version !== SNAPSHOT_VIEW_VERSION || body.provider_called !== false ||
      !["unavailable", "refused", "not_opened", "open"].includes(body.state as string) || !isText(body.statement) ||
      !isText(body.label) || !Number.isInteger(body.selection_limit) || (body.selection_limit as number) < 1 ||
      !Array.isArray(body.rows) || !Array.isArray(body.unusable) || !object(body.filters) ||
      !FILTERS.every((name) => isText((body.filters as Record<string, unknown>)[name]))) return false;
  if (body.state === "unavailable" || body.state === "refused") {
    return isText(body.problem) && body.rows.length === 0 && body.counts === null;
  }
  const pkg = body.package as Package | null;
  if (!object(pkg) || pkg.url !== body.page_url || !SHA.test(pkg.sha256) || !count(pkg.bytes)) return false;
  if (body.state === "not_opened") return body.rows.length === 0 && body.counts === null && body.index === null;
  const rows = body.rows as SnapshotRow[];
  const counts = body.counts as SnapshotView["counts"];
  const index = body.index as SnapshotView["index"];
  if (!object(index) || !SHA.test(index.content_sha256) || !isText(index.extractor_version) || !object(counts) ||
      !rows.every(rowOk) || new Set(rows.map((row) => row.key)).size !== rows.length) return false;
  return counts.usable === rows.length && counts.unusable === body.unusable.length &&
    counts.listed === rows.length + body.unusable.length &&
    COMPLETENESS.every((state) => counts.completeness[state] === rows.filter((row) => row.completeness === state).length) &&
    FILTERS.every((name) => counts.filters[name] === rows.filter((row) => row.filters[name]).length) &&
    (["listed", "missing", "ambiguous"] as const).every((state) =>
      counts.dates[state] === rows.filter((row) => row.date_state === state).length);
}

export function isRecordView(body: unknown, key: string): body is RecordView {
  if (!object(body) || body.view_version !== SNAPSHOT_VIEW_VERSION || body.provider_called !== false ||
      !object(body.record) || !isText(body.completeness) || !object(body.import)) return false;
  const record = body.record as unknown as SnapshotRecord;
  return record.key === key && record.id === `${SNAPSHOT_SOURCE}:${key}` && pressReleaseLink(record.identity) &&
    isText(record.publisher?.title) && texts(record.text?.paragraphs) && COMPLETENESS.includes(record.completeness) &&
    object(record.listing) && ["published", "created", "changed"].every((field) =>
      DATE_STATES.includes((record.listing as unknown as Record<string, ListingTime>)[field]?.state)) &&
    (record.publisher.external_link === null || /^https:\/\//.test(record.publisher.external_link.url)) &&
    Array.isArray(record.same_title) && IMPORT_STATES.includes((body.import as RecordView["import"]).state);
}

function sameKeys(rows: unknown, keys: string[]): rows is PreviewRow[] {
  return Array.isArray(rows) && rows.length === keys.length &&
    rows.every((row, index) => object(row) && row.key === keys[index] && row.id === `${SNAPSHOT_SOURCE}:${keys[index]}` &&
      PREVIEW_STATES.includes(row.state as PreviewRow["state"]) && texts(row.reasons));
}

/** A preview answering exactly for the selected records, in order, with counts that reconcile. */
export function isPreview(body: unknown, keys: string[]): body is Preview {
  if (!object(body) || !object(body.counts) || !isText(body.cost) || typeof body.writes !== "boolean" ||
      !sameKeys(body.rows, keys)) return false;
  const rows = body.rows as PreviewRow[];
  const counts = body.counts as Preview["counts"];
  return PREVIEW_STATES.every((state) => counts[state] === rows.filter((row) => row.state === state).length) &&
    rows.every((row) => row.state !== "changed" || (texts(row.changed) && Number.isInteger(row.version))) &&
    body.writes === (counts.new > 0 || counts.changed > 0);
}

export function isImportResult(body: unknown, keys: string[]): body is ImportResult {
  if (!object(body) || !object(body.counts) || typeof body.written !== "boolean" || !sameKeys(body.rows, keys) ||
      !(body.rows as ImportRow[]).every((row) => OUTCOMES.includes(row.outcome))) return false;
  const rows = body.rows as ImportRow[];
  const counts = body.counts as ImportResult["counts"];
  const written = counts.added + counts.version_added > 0;
  return OUTCOMES.every((outcome) => counts[outcome] === rows.filter((row) => row.outcome === outcome).length) &&
    body.written === written && (written ? isText(body.import_id) : body.import_id === null);
}

// ---------------------------------------------------------------- reading and writing

async function read<T>(path: string, signal: AbortSignal | undefined, check: (body: unknown) => body is T):
    Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const detail = object(body) && typeof body.detail === "string" ? body.detail : `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message: detail };
  if (!response.ok) return { state: "error", message: detail };
  return check(body) ? { state: "ready", data: body } : { state: "error", message: "The reply could not be read by this page." };
}

export type Sent<T> = { state: "done"; data: T } | { state: "refused" | "unconfirmed"; message: string };

async function send<T>(path: string, payload: unknown, check: (body: unknown) => body is T): Promise<Sent<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST", body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Inbox": "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server; nothing was retried. Read the snapshot again to see what the Inbox holds." };
  }
  const body: unknown = await response.json().catch(() => null);
  const detail = object(body) && typeof body.detail === "string" ? body.detail : `Unexpected response (${response.status}).`;
  if (!response.ok) return { state: response.status >= 500 ? "unconfirmed" : "refused", message: detail };
  return check(body) ? { state: "done", data: body } : { state: "unconfirmed", message: "The reply could not be verified." };
}

const BASE = "/api/inbox/snapshots/bis";
export const fetchSnapshot = (signal?: AbortSignal) => read(BASE, signal, isSnapshotView);
export const fetchRecord = (key: string, signal?: AbortSignal) =>
  read(`${BASE}/records/${encodeURIComponent(key)}`, signal, (body): body is RecordView => isRecordView(body, key));
export const openSnapshot = () => send(`${BASE}/open`, {}, isSnapshotView);
export const previewImport = (keys: string[]) =>
  send(`${BASE}/preview`, { keys }, (body): body is Preview => isPreview(body, keys));
export const runImport = (keys: string[], decisions: Record<string, "keep" | "add_version">) =>
  send(`${BASE}/import`, { keys, decisions }, (body): body is ImportResult => isImportResult(body, keys));

// ---------------------------------------------------------------- browsing (local only)

export interface SnapshotFilter {
  query: string; filter: FilterName | "all"; topic: string; text: "any" | "with_text" | "title_only";
  state: "any" | "new" | "imported";
}
/** The first view: semiconductor and advanced-computing records, the content this snapshot is opened for. */
export const DEFAULT_FILTER: SnapshotFilter = { query: "", filter: "semiconductors", topic: "", text: "any", state: "any" };
export const NO_TOPIC = "No topic";
const WITH_TEXT: readonly Completeness[] = ["checked", "checked_differs", "listing_text"];

/** Rows matching every chosen filter; every search word must appear in the title, opening text, topics or host. */
export function filteredRows(rows: SnapshotRow[], filter: SnapshotFilter): SnapshotRow[] {
  const words = filter.query.toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter((row) => {
    const haystack = [row.title, row.opening, ...row.topics, row.external_host ?? ""].join(" ").toLowerCase();
    return words.every((word) => haystack.includes(word)) &&
      (filter.filter === "all" || row.filters[filter.filter]) &&
      (!filter.topic || (filter.topic === NO_TOPIC ? row.topics.length === 0 : row.topics.includes(filter.topic))) &&
      (filter.text === "any" || (filter.text === "with_text") === WITH_TEXT.includes(row.completeness)) &&
      (filter.state === "any" || (filter.state === "new" ? row.import.state === "new" : row.import.state !== "new"));
  }).sort((a, b) => (a.date === null ? 1 : 0) - (b.date === null ? 1 : 0) || (b.date ?? "").localeCompare(a.date ?? "") ||
    a.position - b.position);
}

/** Toggle a record in the selection, never beyond the limit. */
export function toggledKey(selected: string[], key: string, limit: number): string[] {
  if (selected.includes(key)) return selected.filter((item) => item !== key);
  return selected.length >= limit ? selected : [...selected, key];
}

export const COMPLETENESS_SHORT: Record<Completeness, string> = {
  checked: "Text checked against the release page", checked_differs: "Text differs from the release page",
  listing_text: "Listing text, not checked", title_only: "Title only", unreadable: "Text unreadable",
};
export const IMPORT_SHORT: Record<SnapshotRow["import"]["state"], string> = {
  new: "Not imported", imported: "In the Event Inbox", changed: "Imported; the snapshot's version differs",
  unreadable: "Imported entry unreadable",
};

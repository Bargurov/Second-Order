// The case library's list of committed theses (/api/theses), read from the committed files only: no retained source is
// read to list them. Kept apart from thesis.ts so that the library page does not load a thesis's reader until a thesis
// is opened.
import type { Loaded } from "./api";

export const THESIS_CATALOG_VERSION = "thesis-catalog-0.1";
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** One thesis at its latest version; published_on is null when that version is a draft. */
export interface ThesisCatalogEntry { id: string; title: string; topic: string; latest_version: number;
  published_on: string | null; href: string }
export interface ThesisCatalog { view_version: string; theses: ThesisCatalogEntry[]; provider_called: false }

const BODY_KEYS = ["view_version", "theses", "provider_called"];
const ENTRY_KEYS = ["id", "title", "topic", "latest_version", "published_on", "href"];

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
/** An object with exactly these keys, as the thesis reader checks its replies. */
const exactly = (value: unknown, keys: string[]): value is Record<string, unknown> => object(value) &&
  Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isDay = (value: unknown): boolean => typeof value === "string" && DAY.test(value) &&
  !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().startsWith(value);

const entryOk = (entry: unknown): boolean => exactly(entry, ENTRY_KEYS) && typeof entry.id === "string" &&
  ID.test(entry.id) && isText(entry.title) && isText(entry.topic) && Number.isInteger(entry.latest_version) &&
  (entry.latest_version as number) >= 1 && (entry.published_on === null || isDay(entry.published_on)) &&
  entry.href === `/theses/${entry.id}`;

/** The list as served: exactly its fields, each entry well formed and at its own address, listed once, in id order. */
export function isThesisCatalog(body: unknown): body is ThesisCatalog {
  return exactly(body, BODY_KEYS) && body.view_version === THESIS_CATALOG_VERSION && body.provider_called === false &&
    Array.isArray(body.theses) && body.theses.every(entryOk) &&
    body.theses.every((entry, index, all) => index === 0 ||
      (all[index - 1] as ThesisCatalogEntry).id < (entry as ThesisCatalogEntry).id);
}

export async function fetchThesisCatalog(signal: AbortSignal): Promise<Loaded<ThesisCatalog>> {
  let response: Response;
  try {
    response = await fetch("/api/theses", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { state: "error", message: object(body) && typeof body.detail === "string" ? body.detail
      : `Unexpected response (${response.status}).` };
  }
  return isThesisCatalog(body) ? { state: "ready", data: body }
    : { state: "error", message: "The reply could not be read by this page." };
}

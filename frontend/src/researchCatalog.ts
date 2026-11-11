// The case library's list of research views (/api/research), read from the committed files only. Kept apart from
// policyResearch.ts so that the library page does not load a view's reader until a view is opened.
import type { Loaded } from "./api";

export const CATALOG_VERSION = "policy-research-catalog-0.1";
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export interface CatalogEntry { id: string; title: string; question: string; scope_note: string; publications: number;
  comparisons: number; href: string }
export interface Catalog { view_version: string; views: CatalogEntry[]; provider_called: false }

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

export function isCatalog(body: unknown): body is Catalog {
  return object(body) && body.view_version === CATALOG_VERSION && body.provider_called === false &&
    Array.isArray(body.views) && body.views.every((view) => object(view) && isText(view.id) && isText(view.title) &&
      isText(view.question) && isText(view.scope_note) && count(view.publications) && count(view.comparisons) &&
      view.href === `/library/research/${view.id}`) &&
    new Set(body.views.map((view) => (view as CatalogEntry).id)).size === body.views.length;
}

export async function fetchResearchCatalog(signal: AbortSignal): Promise<Loaded<Catalog>> {
  let response: Response;
  try {
    response = await fetch("/api/research", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { state: "error", message: object(body) && typeof body.detail === "string" ? body.detail
      : `Unexpected response (${response.status}).` };
  }
  return isCatalog(body) ? { state: "ready", data: body } : { state: "error", message: "The reply could not be read by this page." };
}

// Related research: links from one event to existing case-library content, selected by the server from local records
// (/api/related-research/events/:kind/:id). The server words every explanation; this module refuses a reply whose links
// break the selection's own rules (an exact-event link without matching address and date, a family or topic link to a
// later case or for an undated event, a repeated target, a historical case already shown above, a misplaced address).
import type { Loaded } from "./api";
import { categorySlug, filtersHref } from "./library.ts";

export const RESEARCH_VIEW_VERSION = "related-research-view-0.1";
export const RELATION_ORDER = ["same_event", "release_family", "topic"] as const;
export type Relation = (typeof RELATION_ORDER)[number];
const MAX_LINKS = 4;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const CHECK_STATES = ["verified", "absent", "different"];
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export interface ResearchLink {
  relation: Relation; relation_label: string;
  target: { collection: "library" | "historical"; id: string; title: string; category: string; date: string;
    date_as_stated: string; href: string };
  explanation: string; differences: string[]; unknown: string[];
  status: { kind: "editorial" | "historical"; prepared_on: string; labels: string[]; source: string;
    source_check: string | null; written_after_event: boolean; timing: string };
  address?: string;
  family?: { slug: string; label: string; event_document: string; case_document: string; more_earlier: number };
  topic?: { slug: string; label: string; found: { term: string; field: string }[] };
}
export interface ResearchView {
  view_version: string; navigation_version: string; kind: "inbox" | "capture"; id: string;
  event: { title: string; date: string | null; date_as_stated: string | null; date_label: string;
    address: string | null; title_only: boolean };
  links: ResearchLink[]; notes: string[]; shown_in_historical: string[]; relations: Record<Relation, string>;
  hints_used: false; written: false; provider_called: false;
}

const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);

function linkOk(link: ResearchLink, event: ResearchView["event"]): boolean {
  if (!object(link) || !RELATION_ORDER.includes(link.relation) || !isText(link.relation_label) ||
      !isText(link.explanation) || !texts(link.differences) || !texts(link.unknown)) return false;
  const target = link.target;
  if (!object(target) || !isText(target.id) || !isText(target.title) || !DAY.test(target.date) ||
      target.href !== (target.collection === "historical" ? `/library/historical/${target.id}`
        : target.collection === "library" ? `/library/${target.id}` : null)) return false;
  const status = link.status;
  if (!object(status) || !texts(status.labels) || status.labels.length === 0 || !isText(status.timing) ||
      !isText(status.source) || typeof status.written_after_event !== "boolean" ||
      (target.collection === "historical") !== (status.kind === "historical") ||
      (status.kind === "historical" ? !CHECK_STATES.includes(status.source_check ?? "") : status.source_check !== null)) {
    return false;
  }
  if (link.relation === "same_event") {
    return event.address !== null && link.address === event.address && event.date === target.date;
  }
  if (event.date === null || target.date > event.date) return false;  // Family and topic: earlier cases only.
  if (link.relation === "release_family") {
    return object(link.family) && isText(link.family.label) && Number.isInteger(link.family.more_earlier) &&
      link.family.more_earlier >= 0;
  }
  return object(link.topic) && isText(link.topic.label) && Array.isArray(link.topic.found) && link.topic.found.length > 0;
}

/** The reply as served, or false: links in strength order, each target once, within the cap and the rules above. */
export function isResearchView(body: unknown): body is ResearchView {
  if (!object(body) || body.view_version !== RESEARCH_VIEW_VERSION || body.written !== false ||
      body.provider_called !== false || body.hints_used !== false || !["inbox", "capture"].includes(body.kind as string) ||
      !isText(body.id) || !object(body.event) || !Array.isArray(body.links) || !texts(body.notes) ||
      !texts(body.shown_in_historical) || body.links.length > MAX_LINKS) return false;
  const event = body.event as ResearchView["event"];
  if (!isText(event.title) || !(event.date === null || DAY.test(event.date))) return false;
  const links = body.links as ResearchLink[];
  if (!links.every((link) => linkOk(link, event))) return false;
  const ranks = links.map((link) => RELATION_ORDER.indexOf(link.relation));
  if (!ranks.every((rank, index) => index === 0 || ranks[index - 1] <= rank)) return false;
  const keys = links.map((link) => `${link.target.collection}:${link.target.id}`);
  if (new Set(keys).size !== keys.length) return false;
  const shown = body.shown_in_historical as string[];
  return !links.some((link) => link.target.collection === "historical" && shown.includes(link.target.id));
}

export async function fetchRelatedResearch(kind: string, id: string, signal: AbortSignal): Promise<Loaded<ResearchView>> {
  let response: Response;
  try {
    response = await fetch(`/api/related-research/events/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`,
                           { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = (object(body) && typeof body.detail === "string" ? body.detail : null) ??
    `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  if (!isResearchView(body)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body };
}

/** The case library filtered to a family link's topic, for the other cases of that family. */
export function familyMoreHref(link: ResearchLink): string | null {
  const slug = categorySlug(link.target.category);
  return link.target.collection === "library" && slug ? filtersHref({ category: slug }) : null;
}

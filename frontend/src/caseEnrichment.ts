// Case enrichment: a source check and reading aid kept beside a case-library case (/api/case-library/:id/enrichment),
// bound by the server to the case file's exact bytes. This module reads replies fail-closed: statuses come from fixed
// lists, an unread document is named only through a declared reference, the counts must equal the checks, every check
// must address a claim of this very case under its own label, and the private copies' locations are never accepted.
import type { Loaded } from "./api";
import type { LibraryCase } from "./library";

export const ENRICHMENT_VIEW_VERSION = "case-enrichment-view-0.1";
export const ASPECTS = ["instrument", "scope", "timing", "conditions"] as const;
export const STATEMENT_STATES = ["stated", "not_stated", "referenced_unread"] as const;
export const CHECK_STATES = ["consistent", "qualified", "discrepancy", "not_found"] as const;
const COPY_STATES = ["verified", "absent", "different"];
const SOURCE_IDS = ["release", "listing"];
const RETAINED_KEYS = ["approval_id", "bytes", "charset", "retrieved_at", "sha256"];
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type Aspect = (typeof ASPECTS)[number];
export type CheckState = (typeof CHECK_STATES)[number];
export interface Statement {
  aspect: Aspect; status: (typeof STATEMENT_STATES)[number]; text: string; source: string; reference: string | null;
}
export interface ClaimCheck { target: string; label: string; status: CheckState; source: string; note: string | null }
export interface EnrichmentSource {
  id: string; role: string; publisher: string; title: string; url: string; date_as_stated: string | null;
  retained: { approval_id: string; sha256: string; bytes: number; retrieved_at: string; charset: string };
}
export interface Enrichment {
  case_file_sha256: string; currency: "historical"; currency_note: string;
  sources: EnrichmentSource[];
  copies: { source: string; state: string; acquisition_record: string; detail: string }[];
  chain: { placement: string; attribution: "curator_interpretation"; basis: string }; chain_label: string;
  readout: Statement[]; aspects: Aspect[];
  references: { id: string; description: string; url: string | null; source: string; read: false }[];
  claim_checks: ClaimCheck[]; counts: Record<CheckState, number>; not_checked: string;
  examination: { channel: string; observations: string[] }[]; examination_note: string;
  comparison: { historical_case: string; title: string; href: string; text: string;
    facts: { id: string; text: string }[] } | null;
  provenance: { prepared_by: string; prepared_on: string; method: string; ai_assisted: true;
    human_review: "not_reviewed"; research_use: "excluded" };
}
export interface EnrichmentView {
  view_version: string; case_id: string; state: "none" | "stale" | "bound"; note: string | null;
  enrichment: Enrichment | null; provider_called: false;
}

const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.length > 0 && value.every(isText);
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const https = (value: unknown): boolean => isText(value) && value.startsWith("https://");

function sourcesOk(sources: unknown): sources is EnrichmentSource[] {
  if (!Array.isArray(sources) || sources.length === 0) return false;
  const ids = sources.map((source) => (object(source) ? source.id : null));
  if (new Set(ids).size !== ids.length || !ids.includes("release")) return false;
  return sources.every((source) => object(source) && SOURCE_IDS.includes(source.id as string) && isText(source.role) &&
    isText(source.title) && isText(source.publisher) && https(source.url) &&
    (source.date_as_stated === null || isText(source.date_as_stated)) && object(source.retained) &&
    JSON.stringify(Object.keys(source.retained).sort()) === JSON.stringify(RETAINED_KEYS) &&
    /^[a-f0-9]{64}$/.test(String(source.retained.sha256)) && Number.isInteger(source.retained.bytes) &&
    (source.retained.bytes as number) > 0 && isText(source.retained.retrieved_at) && isText(source.retained.charset));
}

function enrichmentOk(item: Enrichment): boolean {
  if (!object(item) || item.currency !== "historical" || !isText(item.currency_note) || !sourcesOk(item.sources) ||
      !object(item.chain) || item.chain.attribution !== "curator_interpretation" || !isText(item.chain.placement) ||
      !isText(item.chain.basis) || !isText(item.chain_label) || !isText(item.not_checked) ||
      !isText(item.examination_note) || !object(item.provenance) || item.provenance.ai_assisted !== true ||
      item.provenance.human_review !== "not_reviewed" || item.provenance.research_use !== "excluded" ||
      !Array.isArray(item.readout) || !Array.isArray(item.references) || !Array.isArray(item.claim_checks) ||
      !Array.isArray(item.examination) || item.examination.length === 0 || !Array.isArray(item.copies)) return false;
  const sources = item.sources.map((source) => source.id);
  const references = item.references.map((reference) => (object(reference) ? reference.id : null));
  if (new Set(references).size !== references.length || !item.references.every((reference) =>
    isText(reference.id) && isText(reference.description) && reference.read === false &&
    (reference.url === null || https(reference.url)) && sources.includes(reference.source))) return false;
  // An unread document is named only through a declared reference, and only for a referenced_unread statement.
  if (!item.readout.every((statement) => object(statement) && ASPECTS.includes(statement.aspect) &&
    STATEMENT_STATES.includes(statement.status) && isText(statement.text) && sources.includes(statement.source) &&
    (statement.status === "referenced_unread"
      ? references.includes(statement.reference) : statement.reference === null))) return false;
  if (!ASPECTS.every((aspect) => item.readout.some((statement) => statement.aspect === aspect))) return false;
  const targets = item.claim_checks.map((check) => (object(check) ? check.target : null));
  if (new Set(targets).size !== targets.length || !item.claim_checks.every((check) => isText(check.target) &&
    isText(check.label) && CHECK_STATES.includes(check.status) && sources.includes(check.source) &&
    (check.status === "consistent" ? check.note === null : isText(check.note)))) return false;
  // The counts shown are reconciled with the checks themselves.
  if (!object(item.counts) || !CHECK_STATES.every((state) =>
    item.counts[state] === item.claim_checks.filter((check) => check.status === state).length)) return false;
  if (item.copies.length !== item.sources.length || !item.copies.every((copy, index) =>
    object(copy) && copy.source === item.sources[index].id && COPY_STATES.includes(copy.state) &&
    isText(copy.detail))) return false;
  if (!item.examination.every((entry) => object(entry) && isText(entry.channel) && texts(entry.observations))) {
    return false;
  }
  const comparison = item.comparison;
  return comparison === null || (object(comparison) && isText(comparison.historical_case) &&
    comparison.href === `/library/historical/${comparison.historical_case}` && isText(comparison.title) &&
    isText(comparison.text) && Array.isArray(comparison.facts) && comparison.facts.length > 0 &&
    comparison.facts.every((fact) => isText(fact.id) && isText(fact.text)));
}

/** The reply as served, or false. */
export function isEnrichmentView(body: unknown): body is EnrichmentView {
  if (!object(body) || body.view_version !== ENRICHMENT_VIEW_VERSION || !isText(body.case_id) ||
      body.provider_called !== false || !["none", "stale", "bound"].includes(body.state as string)) return false;
  if (body.state !== "bound") return body.enrichment === null && isText(body.note);
  return body.note === null && enrichmentOk(body.enrichment as Enrichment);
}

/** The case's own label for a checked claim, or null when the address names nothing in this case. */
export function claimLabel(item: LibraryCase, target: string): string | null {
  if (target === "title" || target === "summary") return target === "title" ? "Title" : "Summary";
  const match = /^(key_facts)\[(\d+)\]$|^(channels)\[(\d+)\]\.source_fact$|^(competing_explanations|source_notes)\[(\d+)\]\.detail$/
    .exec(target);
  if (!match) return null;
  if (match[1]) return item.key_facts[Number(match[2])]?.label ?? null;
  if (match[3]) return item.channels[Number(match[4])]?.title ?? null;
  const list = match[5] === "competing_explanations" ? item.competing_explanations : item.source_notes;
  return list[Number(match[6])]?.title ?? null;
}

/** Whether an enrichment describes this very case: every check under the case's own label, every channel in order. */
export function fitsCase(enrichment: Enrichment, item: LibraryCase): boolean {
  return enrichment.claim_checks.every((check) => claimLabel(item, check.target) === check.label) &&
    JSON.stringify(enrichment.examination.map((entry) => entry.channel)) ===
      JSON.stringify(item.channels.map((channel) => channel.title));
}

/** Claims the retained source contradicts, by address: the page flags each one where it appears. */
export function discrepancies(enrichment: Enrichment | null): Map<string, ClaimCheck> {
  return new Map((enrichment?.claim_checks ?? []).filter((check) => check.status === "discrepancy")
    .map((check) => [check.target, check]));
}

export async function fetchCaseEnrichment(id: string, signal: AbortSignal): Promise<Loaded<EnrichmentView>> {
  let response: Response;
  try {
    response = await fetch(`/api/case-library/${encodeURIComponent(id)}/enrichment`,
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
  if (!isEnrichmentView(body) || body.case_id !== id) {
    return { state: "error", message: "The reply could not be read by this page." };
  }
  return { state: "ready", data: body };
}

/**
 * analysis-provenance.ts — fail-closed consumer of the Analysis Basis summary.
 *
 * The basis answers "what did this analysis use?" — which candidate, which
 * records, which context, which provider/model, which prompt and schema
 * contract.  It does NOT answer "was the analysis right?", and no label here
 * may imply that it does.
 *
 * The parser refuses anything it cannot narrow, including an unknown status: a
 * basis the surface cannot describe honestly must render as a refusal, never
 * as a reassuring default.
 */

export const PROVENANCE_STATES = [
  "VERIFIED_CURRENT",
  "SAVED_WITH_OLDER_BASIS",
  "LEGACY_PROVENANCE_UNAVAILABLE",
  "PROVENANCE_INVALID",
] as const;
export type ProvenanceStatus = (typeof PROVENANCE_STATES)[number];

/** Frozen wording — mirrored from analysis_provenance.PROVENANCE_NON_CLAIM. */
export const PROVENANCE_NON_CLAIM =
  "This basis records what the analysis used. It does not verify that the " +
  "model's interpretation is correct.";

export interface ProvenanceRecord {
  source: string;
  title: string;
  title_key: string;
  published_at: string;
  url: string;
  record_id: string;
}

export interface AnalysisProvenance {
  status: ProvenanceStatus;
  changedDimensions: string[];
  problems: string[];
  candidateId: string | null;
  parentClusterId: number | null;
  sourceCount: number | null;
  firstSeenAt: string | null;
  lastUpdatedAt: string | null;
  provider: string | null;
  model: string | null;
  promptVersion: string | null;
  schemaVersion: string | null;
  createdAt: string | null;
  provenanceHash: string | null;
  contextSnapshot: string | null;
  records: ProvenanceRecord[];
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function nullableString(v: unknown): string | null {
  return typeof v === "string" && v !== "" ? v : null;
}

function nullableNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function stringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function parseRecords(v: unknown): ProvenanceRecord[] {
  if (!Array.isArray(v)) return [];
  const out: ProvenanceRecord[] = [];
  for (const raw of v) {
    if (!isRecord(raw)) continue;
    out.push({
      source: String(raw.source ?? ""),
      title: String(raw.title ?? ""),
      title_key: String(raw.title_key ?? ""),
      published_at: String(raw.published_at ?? ""),
      url: String(raw.url ?? ""),
      record_id: String(raw.record_id ?? ""),
    });
  }
  return out;
}

/**
 * Narrow an unknown provenance summary, or return `null` on any violation.
 *
 * Two refusals are deliberate rather than lenient:
 *   * a stale basis MUST name at least one changed dimension — "something
 *     changed, we won't say what" is not a reviewable statement;
 *   * an invalid basis MUST name at least one problem, for the same reason.
 */
export function parseProvenance(raw: unknown): AnalysisProvenance | null {
  if (!isRecord(raw)) return null;
  const status = raw.status;
  if (typeof status !== "string") return null;
  if (!(PROVENANCE_STATES as readonly string[]).includes(status)) return null;
  if (raw.non_claim !== PROVENANCE_NON_CLAIM) return null;

  const changedDimensions = stringArray(raw.changed_dimensions);
  const problems = stringArray(raw.problems);
  if (status === "SAVED_WITH_OLDER_BASIS" && changedDimensions.length === 0) return null;
  if (status === "PROVENANCE_INVALID" && problems.length === 0) return null;

  return {
    status: status as ProvenanceStatus,
    changedDimensions,
    problems,
    candidateId: nullableString(raw.candidate_id),
    parentClusterId: nullableNumber(raw.parent_cluster_id),
    sourceCount: nullableNumber(raw.source_count),
    firstSeenAt: nullableString(raw.candidate_first_seen_at),
    lastUpdatedAt: nullableString(raw.candidate_last_updated_at),
    provider: nullableString(raw.provider),
    model: nullableString(raw.model),
    promptVersion: nullableString(raw.analysis_prompt_version),
    schemaVersion: nullableString(raw.analysis_schema_version),
    createdAt: nullableString(raw.created_at),
    provenanceHash: nullableString(raw.provenance_hash),
    contextSnapshot: nullableString(raw.candidate_context_snapshot),
    records: parseRecords(raw.candidate_records),
  };
}

const _STATUS_LABEL: Record<ProvenanceStatus, string> = {
  // Wording is about INPUTS only.  "Matches current basis" says the stored
  // inputs still equal today's inputs — never that the analysis was right.
  VERIFIED_CURRENT: "Matches current basis",
  SAVED_WITH_OLDER_BASIS: "Saved under an older basis",
  LEGACY_PROVENANCE_UNAVAILABLE: "Basis not captured",
  PROVENANCE_INVALID: "Basis integrity check failed",
};

export function provenanceLabel(status: ProvenanceStatus): string {
  return _STATUS_LABEL[status];
}

const _DIMENSION_LABEL: Record<string, string> = {
  candidate_records: "candidate source records",
  candidate_context: "captured context",
  provider: "provider",
  model: "model",
  prompt_version: "prompt contract",
  schema_version: "output schema",
  candidate_unresolved: "candidate no longer resolvable",
  candidate_link_conflict: "candidate linked to more than one analysis",
};

export function changedDimensionLabel(dimension: string): string {
  return _DIMENSION_LABEL[dimension] ?? dimension;
}

/**
 * Whether the stored basis is intact AND still equals the current one.
 *
 * This is a statement about inputs, not about the analysis: a trustworthy
 * basis means the run can be reconstructed, nothing more.
 */
export function isBasisTrustworthy(status: ProvenanceStatus): boolean {
  return status === "VERIFIED_CURRENT";
}

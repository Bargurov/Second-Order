/**
 * U1 — Universal Event Dossier reader (event-dossier-index-v1 /
 * event-dossier-v1, published by U0).
 *
 * The complete 97-event published historical research universe (65 FOMC +
 * 32 OPEC) rendered as one bounded, publication-ordered ledger: no event
 * is selected, promoted, ranked, or featured, nothing orders by response,
 * percentile, aggregate state, or completeness, and the family filter and
 * text search are outcome-neutral order-preserving subsequences.  Opening
 * an event fetches exactly one dossier (nothing is prefetched), renders
 * its 13 sections in the backend's frozen order under progressive
 * disclosure, keeps aggregate research context visibly aggregate, keeps
 * missingness and the permanent non-claim always visible, and shows G6C
 * material only as separately labeled optional enrichment.
 *
 * Fail-closed: a malformed or wrong-version index renders zero event
 * controls with an explicit contract refusal; a malformed, mismatched, or
 * misaddressed dossier renders zero sections with an explicit refusal
 * while the validated index ledger stays usable.  Damaged input is never
 * sorted, repaired, or partially rendered.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  api,
  type EventDossierDetail,
  type EventDossierIndex,
  type EventDossierIndexEntry,
  type EventDossierSection,
  type EventDossierSourceRef,
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";

/** Ledger rows disclosed per step — the card never mounts all 97 rows
 *  unless the reviewer asks for them page by page. */
export const DOSSIER_LEDGER_PAGE_SIZE = 25;

/** The backend's frozen 13-section order (event-dossier-v1). */
export const DOSSIER_SECTION_ORDER = [
  "identity",
  "source_provenance",
  "eligibility_denominators",
  "mechanism_asset_basis",
  "reaction_observations",
  "reaction_enrichment",
  "ordinary_period_context",
  "aggregate_research_context",
  "robustness_timing_transmission",
  "falsifier_fragility",
  "missingness_limitations",
  "evidence_class_claim_ceiling",
  "non_claim",
] as const;

export type DossierSectionName = (typeof DOSSIER_SECTION_ORDER)[number];

/** Sections whose bodies start disclosed (the reader's recommended
 *  entry path); missingness and the non-claim are never collapsible. */
export const DOSSIER_DEFAULT_OPEN_SECTIONS: readonly DossierSectionName[] = [
  "identity",
  "source_provenance",
  "mechanism_asset_basis",
  "reaction_observations",
  "evidence_class_claim_ceiling",
];

const ALWAYS_VISIBLE_SECTIONS: ReadonlySet<string> = new Set([
  "missingness_limitations",
  "non_claim",
]);

export type DossierFamilyFilter = "All" | "FOMC" | "OPEC";

export type EventDossierContractState = "ok" | "malformed";

// ---------------------------------------------------------------------------
// Frozen contract vocabulary (identities and counts only — never values)
// ---------------------------------------------------------------------------

const INDEX_CONTRACT_VERSION = "event-dossier-index-v1";
const DETAIL_CONTRACT_VERSION = "event-dossier-v1";
const UNIVERSE = "historical_research";
const TOTAL_EVENTS = 97;
const FAMILY_N: Record<string, number> = { FOMC: 65, OPEC: 32 };
const ROWS_PER_EVENT: Record<string, number> = { FOMC: 8, OPEC: 12 };
const ENRICHED_N = 6;
const CORE_N = 91;

const FAMILIES: ReadonlySet<string> = new Set(["FOMC", "OPEC"]);
const TOP_STATUSES: ReadonlySet<string> = new Set([
  "COMPLETE",
  "PARTIAL",
  "UNAVAILABLE",
  "CONTRADICTORY",
]);
const TIERS: ReadonlySet<string> = new Set([
  "published_per_event_dossier",
  "core_published_evidence",
]);
const SECTION_STATUSES: ReadonlySet<string> = new Set([
  "available",
  "structurally_unavailable",
  "not_applicable",
  "not_exposed",
  "unresolved",
  "contradictory",
]);

/** Published aggregate vocabulary that must never become an event
 *  verdict: allowed only inside data subtrees that explicitly carry
 *  `context_scope: "aggregate"`, and never in a field named status.
 *  Every frozen atomic AND compound form is enumerated — protecting a
 *  compound label does not protect its standalone variants. */
const AGGREGATE_LABELS: ReadonlySet<string> = new Set([
  "ELEVATED",
  "ORDINARY",
  "UNRESOLVED",
  "ORDINARY_UNRESOLVED",
  "ORDINARY / UNRESOLVED",
  "PROPAGATED",
  "BROAD MEASUREMENT CONSISTENCY",
  "LOWER-MAGNITUDE",
]);

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function nonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.length > 0;
}

function isCount(v: unknown): v is number {
  return typeof v === "number" && Number.isInteger(v) && v >= 0;
}

function isSourceRef(v: unknown): boolean {
  if (!isRecord(v) || !nonEmptyString(v.artifact)) return false;
  if (v.sha256 !== undefined && !(typeof v.sha256 === "string" && SHA256_RE.test(v.sha256))) {
    return false;
  }
  if (v.bytes !== undefined && !isCount(v.bytes)) return false;
  if (v.note !== undefined && !nonEmptyString(v.note)) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Index validation (fail closed — nothing is repaired or re-sorted)
// ---------------------------------------------------------------------------

function isIndexEntry(v: unknown): v is EventDossierIndexEntry {
  return (
    isRecord(v) &&
    nonEmptyString(v.candidate_id) &&
    typeof v.family === "string" &&
    FAMILIES.has(v.family) &&
    typeof v.event_date === "string" &&
    (v.event_date === "" || DATE_RE.test(v.event_date)) &&
    nonEmptyString(v.anchor_session) &&
    DATE_RE.test(v.anchor_session as string) &&
    typeof v.top_level_status === "string" &&
    TOP_STATUSES.has(v.top_level_status) &&
    isCount(v.available_section_count) &&
    isCount(v.unavailable_section_count) &&
    isCount(v.contradictory_section_count) &&
    v.available_section_count +
      v.unavailable_section_count +
      v.contradictory_section_count ===
      DOSSIER_SECTION_ORDER.length &&
    typeof v.enrichment_tier === "string" &&
    TIERS.has(v.enrichment_tier)
  );
}

/** Exact fail-closed contract for the served index: version and universe
 *  pins, the frozen 97 = 65 + 32 universe with the published 6 / 91
 *  enrichment split, unique identities, the served publication order
 *  (the FOMC block then the OPEC block, each strictly ascending by
 *  anchor session — verified, never re-imposed), full vocabulary checks,
 *  and every coverage tally reconciled against the event rows. */
export function eventDossierIndexState(
  data: EventDossierIndex | undefined,
): EventDossierContractState {
  if (!isRecord(data)) return "malformed";
  if (data.contract_version !== INDEX_CONTRACT_VERSION) return "malformed";
  if (data.universe !== UNIVERSE) return "malformed";
  if (
    !Array.isArray(data.generated_from) ||
    data.generated_from.length === 0 ||
    !data.generated_from.every(isSourceRef)
  ) {
    return "malformed";
  }
  const cov = data.coverage;
  if (!isRecord(cov)) return "malformed";
  const events = data.events;
  if (!Array.isArray(events) || events.length !== TOTAL_EVENTS) {
    return "malformed";
  }
  if (!events.every(isIndexEntry)) return "malformed";

  // ---- unique identities -----------------------------------------------
  const ids = new Set(events.map((e) => e.candidate_id));
  if (ids.size !== TOTAL_EVENTS) return "malformed";

  // ---- served publication order: FOMC block then OPEC block, each
  //      strictly ascending by anchor session --------------------------
  const fomcBlock = events.slice(0, 65);
  const opecBlock = events.slice(65);
  if (!fomcBlock.every((e) => e.family === "FOMC")) return "malformed";
  if (!opecBlock.every((e) => e.family === "OPEC")) return "malformed";
  for (const block of [fomcBlock, opecBlock]) {
    let prevAnchor = "";
    for (const e of block) {
      if (!(e.anchor_session > prevAnchor)) return "malformed";
      prevAnchor = e.anchor_session;
    }
  }

  // ---- coverage reconciliation ----------------------------------------
  const familyTally: Record<string, number> = {};
  const statusTally: Record<string, number> = {
    COMPLETE: 0,
    PARTIAL: 0,
    UNAVAILABLE: 0,
    CONTRADICTORY: 0,
  };
  const tierTally: Record<string, number> = {
    published_per_event_dossier: 0,
    core_published_evidence: 0,
  };
  let contradictorySections = 0;
  for (const e of events) {
    familyTally[e.family] = (familyTally[e.family] ?? 0) + 1;
    statusTally[e.top_level_status] = (statusTally[e.top_level_status] ?? 0) + 1;
    tierTally[e.enrichment_tier] = (tierTally[e.enrichment_tier] ?? 0) + 1;
    contradictorySections += e.contradictory_section_count;
  }
  if (cov.total !== TOTAL_EVENTS) return "malformed";
  const famCounts: unknown = cov.family_counts;
  if (
    !isRecord(famCounts) ||
    Object.keys(famCounts).sort().join("|") !== "FOMC|OPEC" ||
    famCounts.FOMC !== FAMILY_N.FOMC ||
    famCounts.OPEC !== FAMILY_N.OPEC ||
    famCounts.FOMC !== familyTally.FOMC ||
    famCounts.OPEC !== familyTally.OPEC
  ) {
    return "malformed";
  }
  const statusCounts: unknown = cov.status_counts;
  if (
    !isRecord(statusCounts) ||
    Object.keys(statusCounts).sort().join("|") !==
      [...TOP_STATUSES].sort().join("|") ||
    [...TOP_STATUSES].some((s) => statusCounts[s] !== statusTally[s])
  ) {
    return "malformed";
  }
  const tierCounts: unknown = cov.enrichment_counts;
  if (
    !isRecord(tierCounts) ||
    tierCounts.published_per_event_dossier !== ENRICHED_N ||
    tierCounts.core_published_evidence !== CORE_N ||
    tierCounts.published_per_event_dossier !==
      tierTally.published_per_event_dossier ||
    tierCounts.core_published_evidence !== tierTally.core_published_evidence
  ) {
    return "malformed";
  }
  const sectionCounts: unknown = cov.section_availability_counts;
  if (
    !isRecord(sectionCounts) ||
    Object.keys(sectionCounts).sort().join("|") !==
      [...DOSSIER_SECTION_ORDER].sort().join("|")
  ) {
    return "malformed";
  }
  for (const name of DOSSIER_SECTION_ORDER) {
    const tally = sectionCounts[name];
    if (!isRecord(tally)) return "malformed";
    let sum = 0;
    for (const [status, count] of Object.entries(tally)) {
      if (!SECTION_STATUSES.has(status) || !isCount(count)) return "malformed";
      sum += count;
    }
    if (sum !== TOTAL_EVENTS) return "malformed";
  }
  const contradiction = cov.contradiction_counts;
  if (
    !isRecord(contradiction) ||
    contradiction.events !== statusTally.CONTRADICTORY ||
    contradiction.sections !== contradictorySections
  ) {
    return "malformed";
  }
  return "ok";
}

// ---------------------------------------------------------------------------
// Detail validation (fail closed — cross-checked against the index entry)
// ---------------------------------------------------------------------------

function isShapedSection(v: unknown): v is EventDossierSection {
  return (
    isRecord(v) &&
    typeof v.status === "string" &&
    SECTION_STATUSES.has(v.status) &&
    nonEmptyString(v.reason_code) &&
    nonEmptyString(v.summary) &&
    "data" in v &&
    Array.isArray(v.source_references) &&
    v.source_references.length > 0 &&
    v.source_references.every(isSourceRef)
  );
}

/** True when every published aggregate label in the value sits inside an
 *  object subtree that explicitly carries `context_scope: "aggregate"`,
 *  and no field named status carries one anywhere. */
function aggregateLabelsScoped(value: unknown, scoped: boolean): boolean {
  if (Array.isArray(value)) {
    return value.every((v) => aggregateLabelsScoped(v, scoped));
  }
  if (isRecord(value)) {
    const inScope = scoped || value.context_scope === "aggregate";
    return Object.entries(value).every(([key, v]) => {
      if (typeof v === "string" && AGGREGATE_LABELS.has(v)) {
        return inScope && key !== "status" && key !== "top_level_status";
      }
      return aggregateLabelsScoped(v, inScope);
    });
  }
  return true;
}

function isReactionRow(v: unknown): boolean {
  return (
    isRecord(v) &&
    ["horizon", "metric", "response", "abs_mid_rank_pct", "signed_pct"].every(
      (k) => nonEmptyString(v[k]),
    )
  );
}

function isOrdinaryRow(v: unknown, family: string): boolean {
  return (
    isRecord(v) &&
    nonEmptyString(v.cell_key) &&
    (v.cell_key as string).startsWith(`${family}|`) &&
    nonEmptyString(v.horizon) &&
    nonEmptyString(v.metric) &&
    isCount(v.event_n) &&
    isCount(v.reference_n) &&
    nonEmptyString(v.published_memp) &&
    nonEmptyString(v.published_signed_percentile_median) &&
    nonEmptyString(v.event_response) &&
    nonEmptyString(v.abs_mid_rank_pct) &&
    nonEmptyString(v.signed_pct)
  );
}

function isFlipRuns(v: unknown): boolean {
  return isRecord(v) && isCount(v.runs) && isCount(v.flips);
}

/** Exact fail-closed contract for one served dossier: version pin, the
 *  requested id echoed, exactly the 13 sections in frozen order with all
 *  five required fields each, identity / status / tier / section-count
 *  reconciliation against the selected index entry, family-specific
 *  structural states (FOMC 20d structurally unavailable; Mission J
 *  not applicable for OPEC), the enrichment-tier consistency rule, and
 *  aggregate vocabulary confined to explicit aggregate context. */
export function eventDossierDetailState(
  detail: EventDossierDetail | undefined,
  requestedId: string,
  indexEntry: EventDossierIndexEntry | undefined,
): EventDossierContractState {
  if (!isRecord(detail) || indexEntry === undefined) return "malformed";
  if (detail.contract_version !== DETAIL_CONTRACT_VERSION) return "malformed";
  if (
    detail.candidate_id !== requestedId ||
    indexEntry.candidate_id !== requestedId
  ) {
    return "malformed";
  }
  if (
    typeof detail.top_level_status !== "string" ||
    !TOP_STATUSES.has(detail.top_level_status) ||
    detail.top_level_status !== indexEntry.top_level_status
  ) {
    return "malformed";
  }
  if (
    typeof detail.enrichment_tier !== "string" ||
    !TIERS.has(detail.enrichment_tier) ||
    detail.enrichment_tier !== indexEntry.enrichment_tier
  ) {
    return "malformed";
  }
  const sections = detail.sections;
  if (!isRecord(sections)) return "malformed";
  if (
    Object.keys(sections).join("|") !== DOSSIER_SECTION_ORDER.join("|")
  ) {
    return "malformed";
  }
  let available = 0;
  let unavailable = 0;
  let contradictory = 0;
  for (const name of DOSSIER_SECTION_ORDER) {
    const section = sections[name];
    if (!isShapedSection(section)) return "malformed";
    if (!aggregateLabelsScoped(section.data, false)) return "malformed";
    if (section.status === "available") available += 1;
    else if (section.status === "contradictory") contradictory += 1;
    else unavailable += 1;
  }
  if (
    available !== indexEntry.available_section_count ||
    unavailable !== indexEntry.unavailable_section_count ||
    contradictory !== indexEntry.contradictory_section_count
  ) {
    return "malformed";
  }

  const family = indexEntry.family;
  const expectedRows = ROWS_PER_EVENT[family];
  // key inventory verified above — named access is safe from here on
  const sec = (name: DossierSectionName): EventDossierSection =>
    sections[name] as EventDossierSection;

  // ---- identity reconciles with the index entry ------------------------
  const identity = sec("identity");
  if (!["available", "contradictory"].includes(identity.status)) {
    return "malformed";
  }
  const identityData = identity.data;
  if (
    !isRecord(identityData) ||
    identityData.candidate_id !== requestedId ||
    identityData.family !== family ||
    identityData.anchor_session !== indexEntry.anchor_session ||
    ((identityData.event_date as string | undefined) ?? "") !==
      indexEntry.event_date
  ) {
    return "malformed";
  }

  // ---- source provenance: available or explicitly unresolved -----------
  if (!["available", "unresolved"].includes(sec("source_provenance").status)) {
    return "malformed";
  }
  if (sec("source_provenance").status === "available") {
    const prov = sec("source_provenance").data;
    if (
      !isRecord(prov) ||
      !nonEmptyString(prov.source_description) ||
      !nonEmptyString(prov.official_source_reference) ||
      !nonEmptyString(prov.source_artifact) ||
      !nonEmptyString(prov.anchor_quality)
    ) {
      return "malformed";
    }
  }

  // ---- eligibility: separate family denominators -----------------------
  const elig = sec("eligibility_denominators");
  const eligData = elig.data;
  if (
    elig.status !== "available" ||
    !isRecord(eligData) ||
    eligData.family_event_n !== FAMILY_N[family] ||
    !isCount(eligData.family_event_n_attempted) ||
    !isRecord(eligData.reference_n_by_horizon) ||
    !Array.isArray(eligData.available_horizons) ||
    !Array.isArray(eligData.unavailable_horizons) ||
    !nonEmptyString(eligData.eligibility_gate)
  ) {
    return "malformed";
  }
  for (const lane of Object.values(eligData.reference_n_by_horizon)) {
    if (
      !isRecord(lane) ||
      !isCount(lane.reference_n_attempted) ||
      !isCount(lane.reference_n_available) ||
      !isCount(lane.non_overlapping_blocks) ||
      !nonEmptyString(lane.status)
    ) {
      return "malformed";
    }
  }

  // ---- mechanism: canonical family-level mapping -----------------------
  const mech = sec("mechanism_asset_basis");
  const mechData = mech.data;
  if (
    mech.status !== "available" ||
    !isRecord(mechData) ||
    !nonEmptyString(mechData.mechanism_hypothesis) ||
    mechData.scope !== "family_level" ||
    !nonEmptyString(mechData.primary_asset) ||
    !nonEmptyString(mechData.market_benchmark) ||
    !nonEmptyString(mechData.sector_benchmark) ||
    !nonEmptyString(mechData.price_basis_policy) ||
    !nonEmptyString(mechData.claim_ceiling) ||
    !isRecord(mechData.mapping_version) ||
    mechData.mapping_version.status !== "available" ||
    !nonEmptyString(mechData.mapping_version.value)
  ) {
    return "malformed";
  }

  // ---- reaction observations: the family's exact row count -------------
  const reactions = sec("reaction_observations");
  const reactionData = reactions.data;
  if (
    reactions.status !== "available" ||
    !isRecord(reactionData) ||
    !Array.isArray(reactionData.rows) ||
    reactionData.rows.length !== expectedRows ||
    !reactionData.rows.every(isReactionRow) ||
    !nonEmptyString(reactionData.method_note)
  ) {
    return "malformed";
  }

  // ---- enrichment tier consistency -------------------------------------
  const enrichment = sec("reaction_enrichment");
  if (detail.enrichment_tier === "core_published_evidence") {
    if (
      enrichment.status !== "not_exposed" ||
      enrichment.reason_code !== "per_event_reaction_not_published" ||
      enrichment.data !== null
    ) {
      return "malformed";
    }
  } else {
    if (!["available", "contradictory"].includes(enrichment.status)) {
      return "malformed";
    }
    if (enrichment.status === "available") {
      const g6c = enrichment.data;
      if (
        !isRecord(g6c) ||
        !Array.isArray(g6c.readout_rows) ||
        g6c.readout_rows.length !== 4 ||
        !g6c.readout_rows.every(
          (r) =>
            isRecord(r) &&
            nonEmptyString(r.metric) &&
            nonEmptyString(r["1d"]) &&
            nonEmptyString(r["5d"]) &&
            nonEmptyString(r["20d"]),
        ) ||
        !nonEmptyString(g6c.role_in_record) ||
        !nonEmptyString(g6c.source_description) ||
        !nonEmptyString(g6c.source_ledger_reference)
      ) {
        return "malformed";
      }
    }
  }

  // ---- ordinary-period context: joined cells + FOMC 20d structural -----
  const ordinary = sec("ordinary_period_context");
  const ordinaryData = ordinary.data;
  if (
    ordinary.status !== "available" ||
    !isRecord(ordinaryData) ||
    !Array.isArray(ordinaryData.rows) ||
    ordinaryData.rows.length !== expectedRows ||
    !ordinaryData.rows.every((r) => isOrdinaryRow(r, family)) ||
    !nonEmptyString(ordinaryData.method_note)
  ) {
    return "malformed";
  }
  if (family === "FOMC") {
    const fomc20d = ordinaryData.fomc_20d;
    if (
      !isRecord(fomc20d) ||
      fomc20d.status !== "structurally_unavailable" ||
      !nonEmptyString(fomc20d.reason_code)
    ) {
      return "malformed";
    }
  }

  // ---- aggregate research context: explicit aggregate scope ------------
  const aggregate = sec("aggregate_research_context");
  const aggregateData = aggregate.data;
  if (
    aggregate.status !== "available" ||
    !isRecord(aggregateData) ||
    !Array.isArray(aggregateData.contexts) ||
    aggregateData.contexts.length < 2 ||
    !aggregateData.contexts.every(
      (c) =>
        isRecord(c) &&
        c.context_scope === "aggregate" &&
        nonEmptyString(c.source) &&
        nonEmptyString(c.evidence_class),
    ) ||
    !nonEmptyString(aggregateData.non_inheritance_note)
  ) {
    return "malformed";
  }

  // ---- robustness: Mission G always; Mission J FOMC-only ---------------
  const robustness = sec("robustness_timing_transmission");
  const robustnessData = robustness.data;
  if (
    robustness.status !== "available" ||
    !isRecord(robustnessData) ||
    !isRecord(robustnessData.mission_g) ||
    robustnessData.mission_g.context_scope !== "aggregate" ||
    !isRecord(robustnessData.mission_j) ||
    robustnessData.mission_j.context_scope !== "aggregate"
  ) {
    return "malformed";
  }
  const missionJ = robustnessData.mission_j;
  if (family === "FOMC") {
    if (
      missionJ.status !== "available" ||
      !Array.isArray(missionJ.j1b_cells) ||
      missionJ.j1b_cells.length === 0 ||
      !Array.isArray(missionJ.j2_timing_cells) ||
      !Array.isArray(missionJ.j3_edges)
    ) {
      return "malformed";
    }
  } else if (
    missionJ.status !== "not_applicable" ||
    missionJ.reason_code !== "mission_j_fomc_only" ||
    !nonEmptyString(missionJ.note)
  ) {
    return "malformed";
  }

  // ---- falsifier / fragility -------------------------------------------
  const falsifier = sec("falsifier_fragility");
  const falsifierData = falsifier.data;
  if (
    falsifier.status !== "available" ||
    !isRecord(falsifierData) ||
    !nonEmptyString(falsifierData.scope_note) ||
    !nonEmptyString(falsifierData.battery_disclosure) ||
    !Array.isArray(falsifierData.cell_overlays) ||
    falsifierData.cell_overlays.length !== expectedRows ||
    !falsifierData.cell_overlays.every(
      (o) =>
        isRecord(o) &&
        nonEmptyString(o.cell_key) &&
        isFlipRuns(o.f1_loyo) &&
        isFlipRuns(o.f2_loeo) &&
        typeof o.f3_sign_flip === "boolean",
    )
  ) {
    return "malformed";
  }
  if (family === "FOMC" && !isRecord(falsifierData.knife_edge)) {
    return "malformed";
  }
  if (
    family === "OPEC" &&
    (!isRecord(falsifierData.era_bounded_credit) ||
      !nonEmptyString(
        (falsifierData.era_bounded_credit as Record<string, unknown>).note,
      ) ||
      !nonEmptyString(falsifierData.calendar_time_confound))
  ) {
    return "malformed";
  }

  // ---- missingness: a non-empty explicit inventory ---------------------
  const missingness = sec("missingness_limitations");
  const missingnessData = missingness.data;
  if (
    missingness.status !== "available" ||
    !isRecord(missingnessData) ||
    !Array.isArray(missingnessData.items) ||
    missingnessData.items.length === 0 ||
    !missingnessData.items.every(
      (i) =>
        isRecord(i) &&
        nonEmptyString(i.reason_code) &&
        nonEmptyString(i.statement),
    )
  ) {
    return "malformed";
  }

  // ---- evidence classes / claim ceiling --------------------------------
  const evidenceClass = sec("evidence_class_claim_ceiling");
  const evidenceClassData = evidenceClass.data;
  if (
    evidenceClass.status !== "available" ||
    !isRecord(evidenceClassData) ||
    !Array.isArray(evidenceClassData.classes) ||
    evidenceClassData.classes.length < 2 ||
    !evidenceClassData.classes.every(nonEmptyString) ||
    !nonEmptyString(evidenceClassData.pooling_prohibition) ||
    !nonEmptyString(evidenceClassData.claim_ceiling)
  ) {
    return "malformed";
  }

  // ---- the permanent non-claim -----------------------------------------
  const nonClaim = sec("non_claim");
  const nonClaimData = nonClaim.data;
  if (
    nonClaim.status !== "available" ||
    !isRecord(nonClaimData) ||
    !nonEmptyString(nonClaimData.statement)
  ) {
    return "malformed";
  }
  return "ok";
}

// ---------------------------------------------------------------------------
// Pure ledger helpers (outcome-neutral; order always the payload's own)
// ---------------------------------------------------------------------------

/** Stable, order-preserving subsequence filter: family scope plus a text
 *  match on candidate id (substring) or the two displayed dates (exact).
 *  Clearing both inputs returns the exact original publication order. */
export function filterDossierEvents(
  events: EventDossierIndexEntry[],
  family: DossierFamilyFilter,
  search: string,
): EventDossierIndexEntry[] {
  const q = search.trim();
  const ql = q.toLowerCase();
  return events.filter((e) => {
    if (family !== "All" && e.family !== family) return false;
    if (q === "") return true;
    return (
      e.candidate_id.toLowerCase().includes(ql) ||
      e.event_date === q ||
      e.anchor_session === q
    );
  });
}

/** The rows currently disclosed: a pure prefix of the (already
 *  order-preserving) input.  Never sorts, never reorders. */
export function visibleDossierRows(
  events: EventDossierIndexEntry[],
  shown: number,
): EventDossierIndexEntry[] {
  return events.slice(0, Math.max(0, shown));
}

// ---------------------------------------------------------------------------
// Presentation vocabulary
// ---------------------------------------------------------------------------

const SECTION_LABELS: Record<DossierSectionName, string> = {
  identity: "Identity",
  source_provenance: "Source provenance",
  eligibility_denominators: "Eligibility and denominators",
  mechanism_asset_basis: "Mechanism and asset basis",
  reaction_observations: "Reaction observations",
  reaction_enrichment: "Reaction enrichment",
  ordinary_period_context: "Ordinary-period context",
  aggregate_research_context: "Aggregate research context",
  robustness_timing_transmission: "Robustness, timing and transmission",
  falsifier_fragility: "Falsifier and fragility context",
  missingness_limitations: "Missingness and limitations",
  evidence_class_claim_ceiling: "Evidence class and claim ceiling",
  non_claim: "Non-claim",
};

const STATUS_LABELS: Record<string, string> = {
  available: "Available",
  structurally_unavailable: "Structurally unavailable",
  not_applicable: "Not applicable",
  not_exposed: "Not exposed",
  unresolved: "Unresolved",
  contradictory: "Contradictory",
};

const TIER_LABELS: Record<string, string> = {
  published_per_event_dossier: "Published per-event enrichment",
  core_published_evidence: "Core published evidence",
};

const COMPLETE_CLARIFIER =
  "Every required section has an explicit resolved state; some evidence " +
  "may still be structurally unavailable or not exposed.";

const KICKER =
  "font-mono text-[9.5px] uppercase tracking-[0.12em] text-on-surface-variant/55";
const TH =
  "px-2 py-1 text-left font-mono text-[9.5px] font-medium uppercase tracking-[0.08em] text-on-surface-variant/55";
const TD = "px-2 py-1 font-mono text-[11px] tabular-nums";
const SMALL_BUTTON =
  "rounded-sm border border-border/50 px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/70 hover:border-on-surface-variant/50 hover:text-on-surface focus-visible:outline focus-visible:outline-1 focus-visible:outline-primary";

// ---------------------------------------------------------------------------
// Small shared render pieces
// ---------------------------------------------------------------------------

function AggregateTag() {
  return (
    <p className="w-fit border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/80">
      Aggregate context — not an individual-event classification
    </p>
  );
}

function SectionProvenance({ refs }: { refs: EventDossierSourceRef[] }) {
  return (
    <details
      data-dossier-provenance
      className="group rounded-sm border border-border/30 bg-surface-container-lowest/40"
    >
      <summary className="cursor-pointer list-none px-2 py-1 font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/60 [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="mr-1 inline-block group-open:rotate-90">
          ▸
        </span>
        Provenance · {refs.length} tracked reference
        {refs.length === 1 ? "" : "s"}
      </summary>
      <ul className="flex flex-col gap-1.5 border-t border-border/30 px-2 py-1.5">
        {refs.map((r, i) => (
          <li
            key={`${r.artifact}-${i}`}
            className="flex flex-col gap-0.5 break-all font-mono text-[9.5px] leading-relaxed text-on-surface-variant/70"
          >
            <span className="text-on-surface-variant">{r.artifact}</span>
            <span>SHA-256: {r.sha256 ?? "not exposed"}</span>
            <span>bytes: {r.bytes !== undefined ? r.bytes : "not exposed"}</span>
            {r.note !== undefined && <span>{r.note}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The era-bounded HY OAS credit limitation — served as a structured
 *  coverage record, rendered verbatim with its own note. */
function CreditLimitationNote({
  label,
  credit,
}: {
  label: string;
  credit: Record<string, unknown>;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/75">
        {label}: HY OAS state available {String(credit.available)} /{" "}
        {String(credit.of)} events (FOMC {String(credit.fomc_subset)} · OPEC{" "}
        {String(credit.opec_subset)}) · era-bounded · lens status{" "}
        {String(credit.status)} · fragile associations{" "}
        {String(credit.fragile_associations)} / {String(credit.of_associations)}
      </p>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
        {String(credit.note)}
      </p>
    </div>
  );
}

function StateChip({ status }: { status: string }) {
  return (
    <span className="w-fit shrink-0 rounded-full border border-border bg-surface-container px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.06em] text-on-surface-variant">
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Section data views (narrowed AFTER the whole dossier validated ok)
// ---------------------------------------------------------------------------

interface ReactionRowView {
  horizon: string;
  metric: string;
  response: string;
  abs_mid_rank_pct: string;
  signed_pct: string;
}

interface OrdinaryRowView extends ReactionRowView {
  cell_key: string;
  event_n: number;
  reference_n: number;
  published_memp: string;
  published_signed_percentile_median: string;
  event_response: string;
}

interface FlipRunsView {
  runs: number;
  flips: number;
}

// ---------------------------------------------------------------------------
// Section bodies
// ---------------------------------------------------------------------------

function IdentityBody({ data }: { data: Record<string, unknown> }) {
  const conflicts = Array.isArray(data.conflicts)
    ? (data.conflicts as string[])
    : [];
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
      {[
        ["Candidate ID", data.candidate_id],
        ["Family", data.family],
        ["Event date", data.event_date ?? "not resolved"],
        ["Anchor session", data.anchor_session],
        ["Identity status", data.identity_status ?? "contradictory"],
      ].map(([label, value]) => (
        <div key={String(label)} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
          <dt className="text-[11px] text-on-surface-variant/70">{String(label)}</dt>
          <dd className="break-all font-mono text-[11px] tabular-nums text-on-surface">
            {String(value)}
          </dd>
        </div>
      ))}
      {conflicts.map((c) => (
        <div key={c} className="sm:col-span-2">
          <dd className="text-[11px] text-on-surface-variant/85">{c}</dd>
        </div>
      ))}
    </dl>
  );
}

function SourceProvenanceBody({ data }: { data: Record<string, unknown> }) {
  const rows: Array<[string, unknown]> = [
    ["Source description", data.source_description],
    ["Official source reference", data.official_source_reference],
    ["Source artifact", data.source_artifact],
    ["Source row key", data.source_row_key],
    ["Artifact SHA-256", data.artifact_sha256],
    ["Anchor quality", data.anchor_quality],
  ];
  if (data.publication_timestamp !== undefined) {
    rows.push(["Publication timestamp", data.publication_timestamp]);
  }
  if (data.schedule_status !== undefined) {
    rows.push(["Schedule status", data.schedule_status]);
  }
  if (data.ledger_key !== undefined) rows.push(["Ledger key", data.ledger_key]);
  if (data.action_type !== undefined) {
    rows.push(["Action type", data.action_type]);
  }
  return (
    <dl className="flex flex-col">
      {rows.map(([label, value]) => (
        <div
          key={label}
          className="flex flex-col gap-0.5 border-b border-border/30 py-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3"
        >
          <dt className="shrink-0 text-[11px] text-on-surface-variant/70">{label}</dt>
          <dd className="break-all font-mono text-[10.5px] tabular-nums text-on-surface sm:text-right">
            {String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function EligibilityBody({
  data,
  family,
}: {
  data: Record<string, unknown>;
  family: string;
}) {
  const lanes = data.reference_n_by_horizon as Record<
    string,
    Record<string, unknown>
  >;
  return (
    <div className="flex flex-col gap-2">
      <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/85">
        {family} family event denominator:{" "}
        <span className="text-on-surface">
          {String(data.family_event_n)} available
        </span>{" "}
        of {String(data.family_event_n_attempted)} attempted — a separate
        ledger from the other family, never pooled.
      </p>
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[460px] border-collapse">
          <caption className="sr-only">
            Ordinary reference denominators by horizon
          </caption>
          <thead>
            <tr>
              {[
                "horizon",
                "reference N attempted",
                "reference N available",
                "non-overlapping blocks",
                "status",
              ].map((h) => (
                <th key={h} scope="col" className={TH}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(lanes).map(([horizon, lane]) => (
              <tr key={horizon} className="border-t border-border/30">
                <td className={`${TD} text-on-surface`}>{horizon}</td>
                <td className={TD}>{String(lane.reference_n_attempted)}</td>
                <td className={TD}>{String(lane.reference_n_available)}</td>
                <td className={TD}>{String(lane.non_overlapping_blocks)}</td>
                <td className={`${TD} text-on-surface-variant/80`}>
                  {String(lane.status)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/70">
        available horizons: {(data.available_horizons as string[]).join(", ") || "none"} ·
        unavailable horizons: {(data.unavailable_horizons as string[]).join(", ") || "none"}
      </p>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
        Eligibility gate: {String(data.eligibility_gate)}.
      </p>
    </div>
  );
}

function MechanismBody({ data }: { data: Record<string, unknown> }) {
  const mapping = data.mapping_version as Record<string, unknown>;
  return (
    <div className="flex flex-col gap-2">
      <p className="w-fit border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/80">
        Family-level context — not an event-specific causal finding
      </p>
      <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/70">
        mapping {String(mapping.value)} · {String(mapping.source_artifact)}
      </p>
      <p className="text-[11.5px] leading-relaxed text-on-surface/85">
        {String(data.mechanism_hypothesis)}
      </p>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/75">
        {String(data.mechanism_role)}.
      </p>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-3">
        {[
          ["Primary asset", data.primary_asset],
          ["Market benchmark", data.market_benchmark],
          ["Sector benchmark", data.sector_benchmark],
        ].map(([label, value]) => (
          <div key={String(label)} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
            <dt className="text-[11px] text-on-surface-variant/70">{String(label)}</dt>
            <dd className="font-mono text-[11px] text-on-surface">{String(value)}</dd>
          </div>
        ))}
      </dl>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/75">
        Price basis: {String(data.price_basis_policy)}
      </p>
      <p className="text-[11px] italic leading-relaxed text-on-surface-variant/75">
        Claim ceiling: {String(data.claim_ceiling)}
      </p>
    </div>
  );
}

function ReactionObservationsBody({ data }: { data: Record<string, unknown> }) {
  const rows = data.rows as unknown as ReactionRowView[];
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[520px] border-collapse">
          <caption className="sr-only">
            Published per-event observations in publication order
          </caption>
          <thead>
            <tr>
              {["horizon", "metric", "response", "abs_mid_rank_pct", "signed_pct"].map(
                (h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={`${r.horizon}|${r.metric}`}
                className="border-t border-border/30"
              >
                <td className={`${TD} text-on-surface`}>{r.horizon}</td>
                <td className={TD}>{r.metric}</td>
                <td className={TD}>{r.response}</td>
                <td className={TD}>{r.abs_mid_rank_pct}</td>
                <td className={`${TD} text-on-surface-variant/70`}>{r.signed_pct}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-l-2 border-on-surface-variant/50 pl-2 text-[11px] italic leading-relaxed text-on-surface-variant/80">
        {String(data.method_note)}
      </p>
    </div>
  );
}

function EnrichmentBody({ section }: { section: EventDossierSection }) {
  if (section.status === "contradictory") {
    const data = section.data as Record<string, unknown>;
    return (
      <div className="flex flex-col gap-1 font-mono text-[10.5px] tabular-nums text-on-surface-variant/85">
        <p>canonical mapping: {(data.canonical_mapping as string[]).join(" / ")}</p>
        <p>G6C mapping: {(data.g6c_mapping as string[]).join(" / ")}</p>
      </div>
    );
  }
  const data = section.data as Record<string, unknown>;
  const rows = data.readout_rows as Array<Record<string, string>>;
  return (
    <div className="flex flex-col gap-2">
      <p className={KICKER}>Optional enrichment · G6C published per-event dossier</p>
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[460px] border-collapse">
          <caption className="sr-only">G6C four-lens readout</caption>
          <thead>
            <tr>
              {["metric", "1d", "5d", "20d"].map((h) => (
                <th key={h} scope="col" className={TH}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric} className="border-t border-border/30">
                <td className={`${TD} text-on-surface`}>{r.metric}</td>
                <td className={TD}>{r["1d"]}</td>
                <td className={TD}>{r["5d"]}</td>
                <td className={TD}>{r["20d"]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11.5px] leading-relaxed text-on-surface/85">
        {String(data.role_in_record)}
      </p>
      <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant/70">
        {String(data.source_description)} · {String(data.source_ledger_reference)}
      </p>
    </div>
  );
}

function OrdinaryContextBody({ data }: { data: Record<string, unknown> }) {
  const rows = data.rows as unknown as OrdinaryRowView[];
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[760px] border-collapse">
          <caption className="sr-only">
            This event's observations joined to their frozen ordinary-period
            cells
          </caption>
          <thead>
            <tr>
              <th scope="colgroup" colSpan={3} className={TH}>
                cell
              </th>
              <th
                scope="colgroup"
                colSpan={4}
                className={`${TH} border-l border-border/40`}
              >
                Published aggregate
              </th>
              <th
                scope="colgroup"
                colSpan={3}
                className={`${TH} border-l border-border/40`}
              >
                This event's observation
              </th>
            </tr>
            <tr>
              {["cell key", "horizon", "metric"].map((h) => (
                <th key={h} scope="col" className={TH}>
                  {h}
                </th>
              ))}
              {["event N", "reference N", "published MEMP", "published signed pct median"].map(
                (h, i) => (
                  <th
                    key={h}
                    scope="col"
                    className={i === 0 ? `${TH} border-l border-border/40` : TH}
                  >
                    {h}
                  </th>
                ),
              )}
              {["event response", "abs mid-rank pct", "signed pct"].map((h, i) => (
                <th
                  key={h}
                  scope="col"
                  className={i === 0 ? `${TH} border-l border-border/40` : TH}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.cell_key} className="border-t border-border/30">
                <td className={`${TD} text-on-surface`}>{r.cell_key}</td>
                <td className={TD}>{r.horizon}</td>
                <td className={TD}>{r.metric}</td>
                <td className={`${TD} border-l border-border/40`}>{r.event_n}</td>
                <td className={TD}>{r.reference_n}</td>
                <td className={TD}>{r.published_memp}</td>
                <td className={TD}>{r.published_signed_percentile_median}</td>
                <td className={`${TD} border-l border-border/40 text-on-surface`}>
                  {r.event_response}
                </td>
                <td className={TD}>{r.abs_mid_rank_pct}</td>
                <td className={`${TD} text-on-surface-variant/70`}>{r.signed_pct}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/75">
        The published aggregate and this event's observation are separate
        readings of one frozen cell — never collapsed into one verdict.
      </p>
      <p className="border-l-2 border-on-surface-variant/50 pl-2 text-[11px] italic leading-relaxed text-on-surface-variant/80">
        {String(data.method_note)}
      </p>
    </div>
  );
}

/** The FOMC 20d structural unavailability — rendered outside the
 *  disclosure body so the explicit unavailable state is never hidden. */
function Fomc20dNote({ data }: { data: Record<string, unknown> }) {
  const block = data.fomc_20d as Record<string, unknown> | undefined;
  if (block === undefined) return null;
  return (
    <div className="border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 p-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-on-surface">
        FOMC 20d — structurally unavailable
      </p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-on-surface-variant/85">
        {String(block.limitation)}
      </p>
    </div>
  );
}

function AggregateContextBody({ data }: { data: Record<string, unknown> }) {
  const contexts = data.contexts as Array<Record<string, unknown>>;
  return (
    <div className="flex flex-col gap-3">
      {contexts.map((ctx, i) => {
        const source = String(ctx.source);
        const title =
          source === "mission_i"
            ? "Mission I aggregate context"
            : source === "mission_g"
              ? "Mission G aggregate context"
              : `${source} aggregate context`;
        return (
          <div
            key={`${source}-${i}`}
            className="flex flex-col gap-1.5 rounded-md border border-border/40 bg-surface-container-lowest/40 p-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-on-surface">
                {title}
              </p>
              <AggregateTag />
            </div>
            <p className="text-[10.5px] italic leading-relaxed text-on-surface-variant/70">
              {String(ctx.evidence_class)}
            </p>
            {Array.isArray(ctx.family_readouts) &&
              (ctx.family_readouts as Array<Record<string, string>>).map((r) => (
                <p
                  key={r.horizon}
                  className="border-l-2 border-border/60 pl-2 text-[11px] leading-relaxed text-on-surface/85"
                >
                  <span className="font-mono text-[10px] text-on-surface-variant/70">
                    {r.horizon} ·{" "}
                  </span>
                  {r.headline}
                </p>
              ))}
            {Array.isArray(ctx.cell_states) && (
              <div className="overflow-x-auto rounded-md border border-border/40">
                <table className="w-full min-w-[460px] border-collapse">
                  <caption className="sr-only">
                    Published family cell states (aggregate)
                  </caption>
                  <thead>
                    <tr>
                      {["cell key", "MEMP", "direction", "F6 position"].map((h) => (
                        <th key={h} scope="col" className={TH}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(ctx.cell_states as Array<Record<string, unknown>>).map((c) => (
                      <tr
                        key={String(c.cell_key)}
                        className="border-t border-border/30"
                      >
                        <td className={`${TD} text-on-surface`}>{String(c.cell_key)}</td>
                        <td className={TD}>{String(c.memp)}</td>
                        <td className={TD}>{String(c.memp_direction)}</td>
                        <td className={`${TD} text-on-surface-variant/70`}>
                          {String(c.f6_position)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {typeof ctx.statement === "string" && (
              <p className="text-[11.5px] leading-relaxed text-on-surface/85">
                {ctx.statement}
              </p>
            )}
            {typeof ctx.confound_note === "string" && (
              <p className="text-[11px] italic leading-relaxed text-on-surface-variant/75">
                {ctx.confound_note}
              </p>
            )}
            {isRecord(ctx.stability) && (
              <p className="font-mono text-[10px] tabular-nums leading-relaxed text-on-surface-variant/70">
                stability: continuous associations{" "}
                {String((ctx.stability as Record<string, unknown>).continuous_associations)} ·
                LOEO sign reversals{" "}
                {String((ctx.stability as Record<string, unknown>).loeo_sign_reversals)} ·
                LOYO sign reversals{" "}
                {String((ctx.stability as Record<string, unknown>).loyo_sign_reversals)}
              </p>
            )}
          </div>
        );
      })}
      <p className="text-[11px] italic leading-relaxed text-on-surface-variant/75">
        {String(data.non_inheritance_note)}
      </p>
    </div>
  );
}

/** The OPEC Mission J inapplicability — rendered outside the disclosure
 *  body so the explicit not-applicable state is never hidden. */
function MissionJNotApplicableNote({ data }: { data: Record<string, unknown> }) {
  const missionJ = data.mission_j as Record<string, unknown>;
  if (missionJ.status !== "not_applicable") return null;
  return (
    <div className="border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 p-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-on-surface">
        Mission J: Not applicable — Mission J is FOMC-only.
      </p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-on-surface-variant/85">
        {String(missionJ.note)}
      </p>
    </div>
  );
}

function RobustnessBody({ data }: { data: Record<string, unknown> }) {
  const missionG = data.mission_g as Record<string, unknown>;
  const missionJ = data.mission_j as Record<string, unknown>;
  const stability = missionG.stability as Record<string, unknown> | undefined;
  return (
    <div className="flex flex-col gap-3">
      {/* Mission G — its own evidence program, never merged with Mission J */}
      <div className="flex flex-col gap-1.5 rounded-md border border-border/40 bg-surface-container-lowest/40 p-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-on-surface">
            Mission G — historical evidence program
          </p>
          <AggregateTag />
        </div>
        <p className="text-[10.5px] italic leading-relaxed text-on-surface-variant/70">
          {String(missionG.evidence_class)}
        </p>
        {typeof missionG.fomc_null === "string" && (
          <p className="text-[11.5px] leading-relaxed text-on-surface/85">
            {missionG.fomc_null}
          </p>
        )}
        {typeof missionG.bounded_association === "string" && (
          <p className="text-[11.5px] leading-relaxed text-on-surface/85">
            {missionG.bounded_association}
          </p>
        )}
        {isRecord(missionG.credit_limitation) && (
          <CreditLimitationNote
            label="Credit limitation"
            credit={missionG.credit_limitation}
          />
        )}
        {stability !== undefined && (
          <p className="font-mono text-[10px] tabular-nums leading-relaxed text-on-surface-variant/70">
            stability: continuous associations{" "}
            {String(stability.continuous_associations)} · LOEO sign reversals{" "}
            {String(stability.loeo_sign_reversals)} · LOYO sign reversals{" "}
            {String(stability.loyo_sign_reversals)}
          </p>
        )}
      </div>

      {/* Mission J — FOMC-only robustness program */}
      {missionJ.status === "not_applicable" ? (
        <MissionJNotApplicableNote data={data} />
      ) : (
        <div className="flex flex-col gap-2 rounded-md border border-border/40 bg-surface-container-lowest/40 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-on-surface">
              Mission J — robustness program
            </p>
            <AggregateTag />
          </div>
          <p className="text-[10.5px] italic leading-relaxed text-on-surface-variant/70">
            {String(missionJ.evidence_class)}
          </p>

          <p className={KICKER}>J1B · asset and benchmark challenge</p>
          <div className="overflow-x-auto rounded-md border border-border/40">
            <table className="w-full min-w-[620px] border-collapse">
              <caption className="sr-only">J1B cells (aggregate)</caption>
              <thead>
                <tr>
                  {["cell", "measurement", "lens", "role", "events", "label"].map((h) => (
                    <th key={h} scope="col" className={TH}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(missionJ.j1b_cells as Array<Record<string, unknown>>).map((c) => (
                  <tr key={String(c.cell)} className="border-t border-border/30">
                    <td className={TD}>{String(c.cell)}</td>
                    <td className={`${TD} text-on-surface`}>{String(c.measurement)}</td>
                    <td className={TD}>{String(c.lens)}</td>
                    <td className={TD}>{String(c.role)}</td>
                    <td className={TD}>{String(c.events)}</td>
                    <td className={`${TD} text-on-surface-variant/80`}>
                      {String(c.label)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="flex flex-col gap-0.5">
            {(missionJ.j1b_panels as Array<Record<string, unknown>>).map((p) => (
              <li
                key={String(p.role)}
                className="font-mono text-[10px] tabular-nums text-on-surface-variant/75"
              >
                {String(p.role)} · {String(p.modifier)}
              </li>
            ))}
          </ul>
          <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
            {String(missionJ.measurement_limited)}
          </p>
          <p className="text-[11px] italic leading-relaxed text-on-surface-variant/75">
            {String(missionJ.correlated_views_disclosure)}
          </p>

          <p className={KICKER}>J2 · timing and exact-window collisions</p>
          <div className="overflow-x-auto rounded-md border border-border/40">
            <table className="w-full min-w-[420px] border-collapse">
              <caption className="sr-only">J2 timing cells (aggregate)</caption>
              <thead>
                <tr>
                  {["metric", "window", "label"].map((h) => (
                    <th key={h} scope="col" className={TH}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(missionJ.j2_timing_cells as Array<Record<string, unknown>>).map(
                  (c, i) => (
                    <tr
                      key={`${String(c.metric)}-${String(c.window)}-${i}`}
                      className="border-t border-border/30"
                    >
                      <td className={`${TD} text-on-surface`}>{String(c.metric)}</td>
                      <td className={TD}>{String(c.window)}</td>
                      <td className={`${TD} text-on-surface-variant/80`}>
                        {String(c.label)}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
            {String(missionJ.j2_raw_cell_fragility)}
          </p>
          <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/75">
            C1 collision register: {String(missionJ.c1_status)} · C2 OPEC
            collision tags: {String(missionJ.c2_opec_collision_tags)}
          </p>
          <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
            {String(missionJ.c1_note)}
          </p>

          <p className={KICKER}>J3 · transmission readout</p>
          <ul className="flex flex-col gap-1">
            {(missionJ.j3_edges as Array<Record<string, unknown>>).map((e) => (
              <li
                key={String(e.edge)}
                className="font-mono text-[10px] tabular-nums leading-relaxed text-on-surface-variant/80"
              >
                <span className="text-on-surface">{String(e.edge)}</span>{" "}
                {String(e.from)} → {String(e.to)} · state {String(e.state)} ·
                downstream {String(e.downstream_state)} ({String(e.downstream_m_class)},{" "}
                {String(e.downstream_modifier)})
              </li>
            ))}
          </ul>
          <p className="text-[11px] italic leading-relaxed text-on-surface-variant/75">
            {String(missionJ.j3_note)}
          </p>
        </div>
      )}
    </div>
  );
}

function FalsifierBody({ data }: { data: Record<string, unknown> }) {
  const overlays = data.cell_overlays as Array<Record<string, unknown>>;
  const knife = data.knife_edge as Record<string, unknown> | undefined;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
        {String(data.scope_note)}.
      </p>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
        {String(data.battery_disclosure)}
      </p>
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[520px] border-collapse">
          <caption className="sr-only">
            Published falsifier overlays for this event's cells
          </caption>
          <thead>
            <tr>
              {["cell key", "F1 LOYO flips / runs", "F2 LOEO flips / runs", "F3 sign flip"].map(
                (h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {overlays.map((o) => {
              const f1 = o.f1_loyo as unknown as FlipRunsView;
              const f2 = o.f2_loeo as unknown as FlipRunsView;
              return (
                <tr key={String(o.cell_key)} className="border-t border-border/30">
                  <td className={`${TD} text-on-surface`}>{String(o.cell_key)}</td>
                  <td className={TD}>{`${f1.flips} / ${f1.runs}`}</td>
                  <td className={TD}>{`${f2.flips} / ${f2.runs}`}</td>
                  <td className={`${TD} text-on-surface-variant/80`}>
                    {o.f3_sign_flip === true ? "yes" : "no"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {knife !== undefined && (
        <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 p-2 font-mono text-[10.5px] tabular-nums leading-relaxed text-on-surface-variant/85">
          knife-edge cell ({String(knife.scope)}): {String(knife.cell_key)} ·
          MEMP {String(knife.memp)} · F1 LOYO{" "}
          {`${(knife.f1_loyo as FlipRunsView).flips} / ${(knife.f1_loyo as FlipRunsView).runs}`}{" "}
          · F2 LOEO{" "}
          {`${(knife.f2_loeo as FlipRunsView).flips} / ${(knife.f2_loeo as FlipRunsView).runs}`}
        </p>
      )}
      {isRecord(data.era_bounded_credit) && (
        <CreditLimitationNote
          label="Era-bounded credit"
          credit={data.era_bounded_credit}
        />
      )}
      {typeof data.calendar_time_confound === "string" && (
        <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
          Calendar-time confound: {data.calendar_time_confound}
        </p>
      )}
    </div>
  );
}

function MissingnessBody({ data }: { data: Record<string, unknown> }) {
  const items = data.items as Array<Record<string, string>>;
  return (
    <ul className="flex flex-col">
      {items.map((item) => (
        <li
          key={item.reason_code}
          className="flex flex-col gap-0.5 border-b border-border/30 py-1.5 last:border-0"
        >
          <code className="font-mono text-[10px] text-on-surface">
            {item.reason_code}
          </code>
          <span className="text-[11px] leading-relaxed text-on-surface-variant/85">
            {item.statement}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EvidenceClassBody({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-1">
        {(data.classes as string[]).map((c) => (
          <li
            key={c}
            className="flex items-start gap-1.5 text-[11.5px] leading-relaxed text-on-surface/85"
          >
            <span
              aria-hidden
              className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40"
            />
            {c}
          </li>
        ))}
      </ul>
      <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
        {String(data.pooling_prohibition)}
      </p>
      <p className="text-[11px] italic leading-relaxed text-on-surface-variant/75">
        Claim ceiling: {String(data.claim_ceiling)}
      </p>
    </div>
  );
}

function NonClaimBody({ data }: { data: Record<string, unknown> }) {
  return (
    <p className="border-l-2 border-on-surface-variant/60 bg-surface-container-lowest/60 p-2.5 text-[11.5px] italic leading-relaxed text-on-surface/90">
      {String(data.statement)}
    </p>
  );
}

function renderSectionBody(
  name: DossierSectionName,
  section: EventDossierSection,
  family: string,
) {
  const data = section.data;
  switch (name) {
    case "identity":
      return <IdentityBody data={data as Record<string, unknown>} />;
    case "source_provenance":
      return section.status === "available" ? (
        <SourceProvenanceBody data={data as Record<string, unknown>} />
      ) : null;
    case "eligibility_denominators":
      return (
        <EligibilityBody data={data as Record<string, unknown>} family={family} />
      );
    case "mechanism_asset_basis":
      return <MechanismBody data={data as Record<string, unknown>} />;
    case "reaction_observations":
      return <ReactionObservationsBody data={data as Record<string, unknown>} />;
    case "reaction_enrichment":
      return section.status === "not_exposed" ? null : (
        <EnrichmentBody section={section} />
      );
    case "ordinary_period_context":
      return <OrdinaryContextBody data={data as Record<string, unknown>} />;
    case "aggregate_research_context":
      return <AggregateContextBody data={data as Record<string, unknown>} />;
    case "robustness_timing_transmission":
      return <RobustnessBody data={data as Record<string, unknown>} />;
    case "falsifier_fragility":
      return <FalsifierBody data={data as Record<string, unknown>} />;
    case "missingness_limitations":
      return <MissingnessBody data={data as Record<string, unknown>} />;
    case "evidence_class_claim_ceiling":
      return <EvidenceClassBody data={data as Record<string, unknown>} />;
    case "non_claim":
      return <NonClaimBody data={data as Record<string, unknown>} />;
  }
}

/** State facts that must never hide behind a collapsed disclosure: any
 *  non-available section state, the FOMC 20d structural unavailability,
 *  and the OPEC Mission J inapplicability. */
function alwaysVisibleStateNote(
  name: DossierSectionName,
  section: EventDossierSection,
  family: string,
) {
  const notes: React.ReactNode[] = [];
  if (section.status !== "available") {
    notes.push(
      <div
        key="state"
        className="border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 p-2"
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-on-surface">
          {STATUS_LABELS[section.status] ?? section.status}
          {name === "reaction_enrichment" && section.status === "not_exposed"
            ? " — No published richer per-event reaction dossier exists for this event."
            : ""}
        </p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-on-surface-variant/85">
          {section.summary}
        </p>
      </div>,
    );
  }
  if (name === "ordinary_period_context" && family === "FOMC") {
    notes.push(
      <Fomc20dNote key="fomc20d" data={section.data as Record<string, unknown>} />,
    );
  }
  if (name === "robustness_timing_transmission" && family === "OPEC") {
    notes.push(
      <MissionJNotApplicableNote
        key="mission-j"
        data={section.data as Record<string, unknown>}
      />,
    );
  }
  return notes.length > 0 ? <>{notes}</> : null;
}

// ---------------------------------------------------------------------------
// One dossier panel
// ---------------------------------------------------------------------------

interface EventDossierPanelProps {
  dossier: EventDossierDetail;
  indexEntry: EventDossierIndexEntry;
  panelId: string;
  onClose: () => void;
  initialOpenSections?: readonly string[];
}

function EventDossierPanel({
  dossier,
  indexEntry,
  panelId,
  onClose,
  initialOpenSections,
}: EventDossierPanelProps) {
  const [openSections, setOpenSections] = useState<ReadonlySet<string>>(
    () => new Set(initialOpenSections ?? DOSSIER_DEFAULT_OPEN_SECTIONS),
  );
  const labelId = `${panelId}-label`;
  const family = indexEntry.family;

  function toggle(name: string) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  return (
    <section
      id={panelId}
      data-dossier-panel={dossier.candidate_id}
      aria-labelledby={labelId}
      className="flex flex-col gap-3 border-l-2 border-primary/40 bg-surface-container-low p-3"
    >
      {/* Header — identity and explicit states only; never an aggregate
          label and never an outcome. */}
      <div data-dossier-header className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <p className={KICKER}>
              Event dossier · {family} · {TIER_LABELS[dossier.enrichment_tier]}
            </p>
            <p
              id={labelId}
              className="break-all font-mono text-[13px] tracking-[-0.01em] text-on-surface"
            >
              {dossier.candidate_id}
            </p>
          </div>
          <button
            type="button"
            data-dossier-close
            onClick={onClose}
            className={`shrink-0 ${SMALL_BUTTON}`}
          >
            close
          </button>
        </div>
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md bg-white/[0.06] sm:grid-cols-4">
          {[
            ["Event date", indexEntry.event_date || "not resolved"],
            ["Anchor session", indexEntry.anchor_session],
            ["Top-level status", dossier.top_level_status],
            [
              "Sections",
              `${indexEntry.available_section_count} available · ` +
                `${indexEntry.unavailable_section_count} unavailable · ` +
                `${indexEntry.contradictory_section_count} contradictory`,
            ],
          ].map(([label, value]) => (
            <div
              key={label}
              className="flex flex-col gap-0.5 bg-surface-container-lowest/60 p-2"
            >
              <dt className="font-mono text-[8.5px] uppercase tracking-[0.08em] text-on-surface-variant/55">
                {label}
              </dt>
              <dd className="font-mono text-[11px] tabular-nums text-on-surface">
                {value}
              </dd>
            </div>
          ))}
        </dl>
        {dossier.top_level_status === "COMPLETE" && (
          <p className="text-[10.5px] italic leading-relaxed text-on-surface-variant/70">
            COMPLETE is a coverage state, not a result: {COMPLETE_CLARIFIER}
          </p>
        )}
      </div>

      {/* The 13 sections, in the backend's frozen order.  The dossier
          validated ok upstream, so every frozen key is present. */}
      {DOSSIER_SECTION_ORDER.map((name) => {
        const section = dossier.sections[name] as EventDossierSection;
        const alwaysVisible = ALWAYS_VISIBLE_SECTIONS.has(name);
        const isOpen = alwaysVisible || openSections.has(name);
        const bodyId = `${panelId}-${name}`;
        return (
          <section
            key={name}
            data-dossier-section={name}
            aria-labelledby={`${bodyId}-label`}
            className="flex flex-col gap-2 border-t border-border/40 pt-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h4
                  id={`${bodyId}-label`}
                  className="font-headline text-[12.5px] font-semibold tracking-[-0.01em] text-on-surface"
                >
                  {SECTION_LABELS[name]}
                </h4>
                <StateChip status={section.status} />
              </div>
              {!alwaysVisible && (
                <button
                  type="button"
                  data-dossier-toggle={name}
                  aria-expanded={isOpen}
                  aria-controls={bodyId}
                  onClick={() => toggle(name)}
                  className={SMALL_BUTTON}
                >
                  {isOpen ? "collapse" : "expand"}
                </button>
              )}
            </div>
            {alwaysVisibleStateNote(name, section, family)}
            {isOpen && (
              <div id={bodyId} className="flex flex-col gap-2">
                <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
                  {section.summary}
                </p>
                {renderSectionBody(name, section, family)}
              </div>
            )}
            <SectionProvenance refs={section.source_references} />
          </section>
        );
      })}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Lazy dossier loader — mounted ONLY while an event is open, so a closed
// ledger registers no detail query and issues no request.
// ---------------------------------------------------------------------------

interface OpenDossierLoaderProps {
  candidateId: string;
  indexEntry: EventDossierIndexEntry | undefined;
  panelId: string;
  onClose: () => void;
  initialOpenSections?: readonly string[];
}

function OpenDossierLoader({
  candidateId,
  indexEntry,
  panelId,
  onClose,
  initialOpenSections,
}: OpenDossierLoaderProps) {
  const { data, isPending, isError } = useQuery({
    queryKey: qk.eventDossierDetail(candidateId),
    queryFn: () => api.eventDossier(candidateId),
    staleTime: 1_800_000,
  });
  if (isPending) {
    return (
      <p className="border-l-2 border-border/60 bg-surface-container-low p-3 font-mono text-[10.5px] text-on-surface-variant/70">
        Fetching the {candidateId} dossier…
      </p>
    );
  }
  if (isError) {
    return (
      <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3 text-[11.5px] leading-relaxed text-on-surface-variant/85">
        The dossier for {candidateId} is unavailable (contract error or
        drift). No sections are rendered in its place; the event ledger
        above stays valid.
      </p>
    );
  }
  if (eventDossierDetailState(data, candidateId, indexEntry) !== "ok") {
    return (
      <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3 text-[11.5px] leading-relaxed text-on-surface-variant/85">
        The served dossier for {candidateId} did not match the
        event-dossier-v1 contract. No dossier sections are rendered in its
        place; the event ledger above stays valid.
      </p>
    );
  }
  return (
    <EventDossierPanel
      dossier={data}
      indexEntry={indexEntry as EventDossierIndexEntry}
      panelId={panelId}
      onClose={onClose}
      initialOpenSections={initialOpenSections}
    />
  );
}

// ---------------------------------------------------------------------------
// The card
// ---------------------------------------------------------------------------

const PANEL_DOM_ID = "event-dossier-panel";

export interface UniversalEventDossiersCardProps {
  /** Settled index payload; undefined while loading. */
  data: EventDossierIndex | undefined;
  /** True when the index query settled in error. */
  unavailable?: boolean;
  /** Starting open event (documented static-render test seam; the live
   *  path opens through the ledger buttons). */
  initialOpenCandidateId?: string;
  initialFamilyFilter?: DossierFamilyFilter;
  initialSearch?: string;
  initialRowsShown?: number;
  initialOpenSections?: readonly string[];
}

export function UniversalEventDossiersCard({
  data,
  unavailable = false,
  initialOpenCandidateId,
  initialFamilyFilter,
  initialSearch,
  initialRowsShown,
  initialOpenSections,
}: UniversalEventDossiersCardProps) {
  const [family, setFamily] = useState<DossierFamilyFilter>(
    initialFamilyFilter ?? "All",
  );
  const [search, setSearch] = useState(initialSearch ?? "");
  const [shown, setShown] = useState(
    initialRowsShown ?? DOSSIER_LEDGER_PAGE_SIZE,
  );
  // Explicit selection rule: the family filter and search govern the
  // LEDGER only — they never open, change, or close the selected dossier.
  // A dossier closes only through its close control.
  const [selected, setSelected] = useState<string | null>(
    initialOpenCandidateId ?? null,
  );

  if (unavailable) {
    return (
      <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3 text-[11.5px] leading-relaxed text-on-surface-variant/85">
        The universal event dossier index is unavailable (tracked-contract
        error or drift). No event ledger is shown in its place.
      </p>
    );
  }
  if (data === undefined) {
    return (
      <p className="border-l-2 border-border/60 bg-surface-container-low p-3 font-mono text-[10.5px] text-on-surface-variant/70">
        Loading the tracked dossier index…
      </p>
    );
  }
  if (eventDossierIndexState(data) !== "ok") {
    return (
      <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3 text-[11.5px] leading-relaxed text-on-surface-variant/85">
        The served payload did not match the event-dossier-index-v1
        contract. No event ledger is shown in its place, and no event
        controls are rendered.
      </p>
    );
  }

  const cov = data.coverage;
  const filtered = filterDossierEvents(data.events, family, search);
  const rows = visibleDossierRows(filtered, shown);
  const selectedEntry =
    selected === null
      ? undefined
      : data.events.find((e) => e.candidate_id === selected);

  function setFamilyFilter(next: DossierFamilyFilter) {
    setFamily(next);
    setShown(DOSSIER_LEDGER_PAGE_SIZE);
  }

  function setSearchQuery(next: string) {
    setSearch(next);
    setShown(DOSSIER_LEDGER_PAGE_SIZE);
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Coverage header — payload counts only, reconciled by the
          validator; publication order stated once, up front. */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] tabular-nums text-on-surface-variant/80">
          <span className="text-on-surface">{cov.total} historical events</span>
          <span>{cov.family_counts.FOMC} FOMC</span>
          <span>{cov.family_counts.OPEC} OPEC</span>
          <span>{cov.status_counts.COMPLETE} complete dossiers</span>
          <span>
            {cov.enrichment_counts.published_per_event_dossier} published
            per-event enrichments
          </span>
          <span>
            {cov.enrichment_counts.core_published_evidence} core evidence
            records
          </span>
        </div>
        {(cov.status_counts.PARTIAL > 0 ||
          cov.status_counts.UNAVAILABLE > 0 ||
          cov.status_counts.CONTRADICTORY > 0) && (
          <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/80">
            non-complete dossiers: {cov.status_counts.PARTIAL} partial ·{" "}
            {cov.status_counts.UNAVAILABLE} unavailable ·{" "}
            {cov.status_counts.CONTRADICTORY} contradictory
          </p>
        )}
        <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
          Publication order. No outcome-based ranking or case selection.
        </p>
        <p className="text-[10.5px] italic leading-relaxed text-on-surface-variant/70">
          COMPLETE is a coverage state, not a result: {COMPLETE_CLARIFIER}
        </p>
      </div>

      {/* Scope + search controls — outcome-neutral; the ledger always
          reads in publication order. */}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div
          role="group"
          aria-label="Family scope"
          className="flex items-center gap-1"
        >
          {(["All", "FOMC", "OPEC"] as const).map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={family === f}
              onClick={() => setFamilyFilter(f)}
              className={
                family === f
                  ? `${SMALL_BUTTON} border-on-surface-variant/60 text-on-surface`
                  : SMALL_BUTTON
              }
            >
              {f}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-0.5">
          <label
            htmlFor="event-dossier-search"
            className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/55"
          >
            Search candidate ID or exact date
          </label>
          <input
            id="event-dossier-search"
            type="search"
            value={search}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="fomc-… · opec-… · YYYY-MM-DD"
            className="w-64 rounded-sm border border-border/50 bg-surface-container-lowest px-2 py-1 font-mono text-[11px] text-on-surface placeholder:text-on-surface-variant/40 focus-visible:outline focus-visible:outline-1 focus-visible:outline-primary"
          />
        </div>
      </div>

      {/* The bounded event ledger */}
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[720px] border-collapse">
          <caption className="sr-only">
            Universal event dossier ledger in publication order
          </caption>
          <thead>
            <tr>
              {[
                "Event date",
                "Anchor session",
                "Family",
                "Candidate ID",
                "Status",
                "Enrichment",
                "Sections",
              ].map((h) => (
                <th key={h} scope="col" className={TH}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr
                key={e.candidate_id}
                data-dossier-row={e.candidate_id}
                className="border-t border-border/30"
              >
                <td className={TD}>{e.event_date || "—"}</td>
                <td className={TD}>{e.anchor_session}</td>
                <td className={TD}>{e.family}</td>
                <td className={`${TD} whitespace-nowrap`}>
                  <button
                    type="button"
                    data-dossier-open={e.candidate_id}
                    aria-expanded={selected === e.candidate_id}
                    aria-controls={PANEL_DOM_ID}
                    onClick={() => setSelected(e.candidate_id)}
                    className="font-mono text-[11px] text-on-surface underline decoration-border underline-offset-2 hover:decoration-on-surface-variant focus-visible:outline focus-visible:outline-1 focus-visible:outline-primary"
                  >
                    {e.candidate_id}
                  </button>
                </td>
                <td className={`${TD} text-on-surface-variant/85`}>
                  {e.top_level_status}
                </td>
                <td className={`${TD} text-on-surface-variant/85`}>
                  {TIER_LABELS[e.enrichment_tier]}
                </td>
                <td className={`${TD} text-on-surface-variant/70`}>
                  {`${e.available_section_count} · ${e.unavailable_section_count} · ${e.contradictory_section_count}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/70">
          Showing {rows.length} of {filtered.length} events · publication
          order · Sections column: available · unavailable · contradictory
        </p>
        {rows.length < filtered.length && (
          <button
            type="button"
            onClick={() =>
              setShown((s) =>
                Math.min(s + DOSSIER_LEDGER_PAGE_SIZE, filtered.length),
              )
            }
            className={SMALL_BUTTON}
          >
            show{" "}
            {Math.min(DOSSIER_LEDGER_PAGE_SIZE, filtered.length - rows.length)}{" "}
            more
          </button>
        )}
      </div>

      {/* Exactly one dossier at a time; closing unmounts the loader and
          its panel.  Keyed by candidate so switching events remounts the
          disclosure state cleanly. */}
      {selected !== null && (
        <OpenDossierLoader
          key={selected}
          candidateId={selected}
          indexEntry={selectedEntry}
          panelId={PANEL_DOM_ID}
          onClose={() => setSelected(null)}
          initialOpenSections={initialOpenSections}
        />
      )}
    </div>
  );
}

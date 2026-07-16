/**
 * M3 — reviewer guide contract: verification-path manifest + claim-ceiling
 * glossary for the Evidence Overview disclosure.
 *
 * Pure and deterministic: no React, no fetch, no browser global, no wall
 * clock.  The glossary carries exactly the eight frozen terms a skeptical
 * reviewer meets on this page; every definition is taken (verbatim or
 * minimally compressed, operative rule and non-claim preserved) from the
 * tracked research contracts — chiefly stats/J0_FOMC_ROBUSTNESS_
 * CONSTITUTION.md — and each entry names its source document and section.
 * No definition is invented, softened, or converted into confidence
 * language.
 *
 * The verification manifest traces exactly the four material evidence
 * lanes shown on the page to their canonically recorded provenance.  It
 * consumes the same canonical constants and Mission G / Mission J query
 * payloads the page already renders (no second fetch): a field the
 * canonical source does not record says "not recorded"; a still-loading
 * contract says "preparing tracked record"; a settled-error contract says
 * "record unavailable".  Nothing is inferred from Git HEAD, filenames,
 * README ordering, routes, or timestamps.  Reproduction commands are inert
 * strings for display as code — never executable controls.
 */
import type { MissionGEvidenceSummary, MissionJEvidenceSummary } from "./api";
import type { EvidenceQuerySnapshot } from "./research-record-memo";
import { ACCEPTED_CORPUS as AC, FAMILY_COVERAGE as FC } from "./accepted-corpus";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "./effective-independent-evidence";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "./mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "./representative-case-library";

// ---------------------------------------------------------------------------
// Glossary — eight frozen terms, stable order.
// ---------------------------------------------------------------------------

export interface GlossaryEntry {
  term: string;
  /** Reviewer-facing definition — operative frozen rule preserved. */
  definition: string;
  /** Tracked source document. */
  source: string;
  /** Section or contract inside the source. */
  sourceSection: string;
  /** Explicit claim boundary / non-claim. */
  boundary: string;
}

const J0 = "stats/J0_FOMC_ROBUSTNESS_CONSTITUTION.md";

export const EVIDENCE_GLOSSARY: ReadonlyArray<GlossaryEntry> = [
  {
    term: "MEMP",
    definition:
      "Median event magnitude percentile. Each event's absolute response is placed in the cell's frozen ordinary reference distribution by the mid-rank rule (exact ties contribute one half each); MEMP is the median of those per-event percentiles across the cell's events, and the calibration position C is the mid-rank percentile of the observed MEMP within its frozen era-matched placement distribution. Descriptive placement only.",
    source: J0,
    sourceSection: "section 4.1 (the I0 section-13 / I2B mid-rank rule verbatim)",
    boundary:
      "Not a p-value, not a probability of success, and not significance vocabulary — the frozen design declares no p-values and no FDR pool.",
  },
  {
    term: "ELEVATED",
    definition:
      "Frozen state A, exactly: M > 0.5 AND calibration position C > 0.75 — response magnitude is above ordinary-period central tendency and lies on the upper side of the frozen placement calibration distribution.",
    source: J0,
    sourceSection: "section 4.2, State A",
    boundary:
      "Not statistical significance, not a positive return, not a causal effect, and not an investment opportunity.",
  },
  {
    term: "ORDINARY / UNRESOLVED",
    definition:
      "Frozen state B, exactly: 0.25 <= C <= 0.75 (boundaries inclusive), regardless of whether M is slightly above or below 0.5 — the frozen response measures do not support a special-response classification, and an M of 0.53, 0.51, or 0.48 with C inside the central 50% is never narrated as a special response.",
    source: J0,
    sourceSection: "sections 4.2 (State B) and 4.3 (boundary discipline)",
    boundary:
      'Not "no effect": the state asserts that the frozen measures support no special-response classification, never that a response was absent.',
  },
  {
    term: "PROPAGATED",
    definition:
      "Frozen edge state: the upstream role reads ACTIVATED and the downstream role supports the ELEVATED edge claim under its frozen measurement rule, so the edge receives the descriptive PROPAGATED state — the frozen upstream and downstream roles show aligned elevated-response states.",
    source: J0,
    sourceSection: "section 5, edge state 1 (applied in stats/J3_MECHANISM_TRANSMISSION_READOUT.md)",
    boundary:
      "Descriptive alignment under frozen measurement rules — not proof that transmission occurred.",
  },
  {
    term: "BROAD MEASUREMENT CONSISTENCY",
    definition:
      "Role-level evidence modifier: all usable frozen measurements or proxies of the role agree on the same role-level reading, so the reading does not rest on one proxy. Modifiers are reported side by side and never combined into a score.",
    source: J0,
    sourceSection: "section 6.5 (role-level evidence modifiers)",
    boundary: "The measurements are correlated views, not independent replications.",
  },
  {
    term: "Class B evidence",
    definition:
      "Post-outcome, prospectively frozen robustness evidence: every new Mission J test was frozen before its new result was inspected, and it runs on the same historical sample — robustness evidence only.",
    source: J0,
    sourceSection: "section 3.2 (outcome-exposure constitution)",
    boundary: "Never independent historical confirmation.",
  },
  {
    term: "measurement-limited",
    definition:
      "The preferred or ideal measure for a role is unavailable, so the reading rests on a bounded substitute of a lower measurement class — for the rates role, the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate, and the reading rests on an M2 official series plus an M3 investable proxy. The limitation travels with every affected statement.",
    source: J0,
    sourceSection:
      "sections 7-8 (M1/M2/M3 adjudicability), restated in the J1B publication and the Mission J contract",
    boundary:
      'Not "approximately confirmed": a bounded substitute reading never upgrades to the ideal measure\'s claim.',
  },
  {
    term: "unadjudicable",
    definition:
      "A required source, register or measure is absent, so the frozen question cannot receive a supported classification — no source-pinned BLS release register covers the frozen era, so the C1 CPI / Employment Situation collision branch is unadjudicable in the published execution and no substitute calendar is fetched.",
    source: "stats/J2_TIMING_COLLISION_RESULTS.md",
    sourceSection: "section 6 (collision qualification), under the J0 section-11 collision constitution",
    boundary:
      "Absence of adjudication is not evidence that the condition was absent — freedom from those releases is not certified.",
  },
];

// ---------------------------------------------------------------------------
// Verification-path manifest — four material lanes, stable order.
// ---------------------------------------------------------------------------

export interface VerificationField {
  label: string;
  value: string;
  /** Render as inert code text (reproduction commands, artifact hashes). */
  code?: boolean;
}

export interface VerificationLane {
  lane: string;
  purpose: string;
  scope: string;
  availability: string;
  fields: VerificationField[];
}

const NOT_RECORDED = "not recorded";
const PENDING = "preparing tracked record";
const UNAVAILABLE = "record unavailable";
const STATIC_AVAILABLE = "available — static tracked snapshot";
const CONTRACT_AVAILABLE = "available — tracked contract";

/** Strip the payload's markdown bold markers for plain display (the card's
 *  existing treatment); wording is otherwise untouched. */
function plain(text: string): string {
  return text.replace(/\*\*/g, "");
}

function laneToken(query: EvidenceQuerySnapshot<unknown>): string | null {
  if (query.isPending) return PENDING;
  if (query.isError || query.data === undefined) return UNAVAILABLE;
  return null;
}

function acceptedLane(): VerificationLane {
  return {
    lane: "Accepted archive and denominator record",
    purpose:
      "Canonical denominators and the two named outcome ledgers over the live accepted archive — the figures the denominator ledger below renders.",
    scope: `${AC.savedEvents} archive rows · ${AC.coverageDenominator} accepted coverage rows · ${AC.trackRecordTotal} accepted track-record rows (snapshot)`,
    availability: STATIC_AVAILABLE,
    fields: [
      {
        label: "Source document",
        value: `${NOT_RECORDED} (dated snapshot restated read-only from the live archive)`,
      },
      { label: "Source commit", value: NOT_RECORDED },
      { label: "As of", value: AC.restatedOn },
      { label: "Reproduce (any-support OR-rule ledger)", value: AC.orRuleRepro, code: true },
      {
        label: "Reproduce (directional-majority ledger)",
        value: AC.directionalMajority.repro,
        code: true,
      },
      {
        label: "Evidence ceiling",
        value:
          "Descriptive archive evidence under two named outcome lenses — evidence sufficiency, not a success verdict and not a claim about future events.",
      },
    ],
  };
}

function missionGLane(query: EvidenceQuerySnapshot<MissionGEvidenceSummary>): VerificationLane {
  const token = laneToken(query);
  const base = {
    lane: "Mission G historical record",
    purpose:
      "Frozen-design historical program: whether pre-event market state conditioned event reactions across two bounded historical universes — a separate ledger, never pooled with the accepted track record.",
  };
  if (token !== null) {
    return {
      ...base,
      scope: token,
      availability: token,
      fields: [
        { label: "Contract", value: "GET /evidence/mission-g (tracked artifacts parsed at request time)" },
        { label: "Source artifacts", value: token },
        { label: "Source commit", value: token },
        { label: "Artifact hashes", value: token },
        { label: "Computation / restatement date", value: token },
        { label: "Reproduce", value: token },
        { label: "Evidence ceiling", value: token },
      ],
    };
  }
  const g = query.data as MissionGEvidenceSummary;
  const arts = g.source_artifacts;
  return {
    ...base,
    scope: `${g.lanes.historical.total} historical events — ${g.lanes.historical.fomc_frame_complete} FOMC frame-complete · ${g.lanes.historical.opec_designed_contrast} OPEC designed-contrast; the ${g.lanes.accepted_track_record.count} accepted rows stay a separate lane`,
    availability: CONTRACT_AVAILABLE,
    fields: [
      {
        label: "Contract",
        value: `${g.contract_version} via GET /evidence/mission-g (tracked artifacts parsed at request time)`,
      },
      {
        label: "Source artifacts",
        value: `${arts.readout} · ${arts.stability} · ${arts.cases} · ${arts.promotion_proof} · ${arts.mechanism_attrition}`,
        code: true,
      },
      { label: "Source commit", value: NOT_RECORDED },
      { label: "Artifact hashes", value: NOT_RECORDED },
      { label: "Computation / restatement date", value: NOT_RECORDED },
      { label: "Reproduce", value: NOT_RECORDED },
      { label: "Evidence ceiling", value: g.non_claims[0] ?? NOT_RECORDED },
    ],
  };
}

function missionJLane(query: EvidenceQuerySnapshot<MissionJEvidenceSummary>): VerificationLane {
  const token = laneToken(query);
  const base = {
    lane: "Mission J robustness and transmission record",
    purpose:
      "Hindsight-controlled robustness and transmission program over the completed FOMC 1d finding — a separate ledger, never pooled with Mission G or the accepted archive.",
  };
  if (token !== null) {
    return {
      ...base,
      scope: token,
      availability: token,
      fields: [
        { label: "Contract", value: "GET /evidence/mission-j (tracked publications parsed at request time)" },
        { label: "J1B artifact", value: token },
        { label: "J2 artifact", value: token },
        { label: "J3 artifact", value: token },
        { label: "Publication status", value: token },
        { label: "Computation / restatement date", value: token },
        { label: "Reproduce", value: token },
        { label: "Evidence ceiling", value: token },
      ],
    };
  }
  const j = query.data as MissionJEvidenceSummary;
  const src = j.provenance.sources;
  const classB = j.j3.supports.find((s) => s.includes("Class B"));
  const ceiling = j.j3.supports.find((s) => s.includes("mechanism-consistent descriptive pattern"));
  const ceilingValue =
    classB || ceiling ? plain([classB, ceiling].filter(Boolean).join(" ")) : NOT_RECORDED;
  return {
    ...base,
    scope: `${j.j2.collisions.primary_n} frame-complete FOMC decisions — J1B asset/benchmark, J2 timing/collision, and J3 mechanism readout as separate published sections`,
    availability: CONTRACT_AVAILABLE,
    fields: [
      {
        label: "Contract",
        value: `${j.contract_version} via GET /evidence/mission-j (tracked publications parsed at request time)`,
      },
      {
        label: "J1B artifact",
        value: `${src.j1b.artifact} — sha256 ${src.j1b.sha256} · ${src.j1b.bytes} bytes`,
        code: true,
      },
      {
        label: "J2 artifact",
        value: `${src.j2.artifact} — sha256 ${src.j2.sha256} · ${src.j2.bytes} bytes`,
        code: true,
      },
      {
        label: "J3 artifact",
        value: `${src.j3.artifact} — sha256 ${src.j3.sha256} · ${src.j3.bytes} bytes`,
        code: true,
      },
      { label: "Publication status", value: j.provenance.publication_status },
      { label: "Computation / restatement date", value: NOT_RECORDED },
      { label: "Reproduce", value: NOT_RECORDED },
      { label: "Evidence ceiling", value: ceilingValue },
    ],
  };
}

function staticEvidenceLane(): VerificationLane {
  return {
    lane: "Mechanism-family / independence / representative-case static evidence",
    purpose:
      "Static, dated snapshots of the read-only research reports surfaced below — the independence caution (K2), the mechanism-family evidence inventory (E1), the representative research set (F1/F2), and family coverage (AZ1).",
    scope: `${EIE.acceptedTrackRecordRows} accepted rows in ${EIE.clusterCount} market-story clusters · ${MFE.buckets.sum} rows by tested headline overlay · ${RCL.totals.total} illustrative cases · ${FC.stagedCandidates} staged candidates kept outside accepted denominators`,
    availability: STATIC_AVAILABLE,
    fields: [
      {
        label: "Independence caution (K2)",
        value: `${EIE.sourceDoc} @ ${EIE.sourceCommit}`,
        code: true,
      },
      { label: "Reproduce (independence caution)", value: EIE.reproCommand, code: true },
      {
        label: "Family inventory (E1)",
        value: `${MFE.sourceDoc} @ ${MFE.sourceCommit}`,
        code: true,
      },
      { label: "Reproduce (family inventory)", value: MFE.reproCommand, code: true },
      {
        label: "Representative cases (F1/F2)",
        value: `${RCL.sources[0]} · ${RCL.sources[1]} @ ${RCL.sourceCommit} (outcomes restated ${RCL.outcomesRestatedOn})`,
        code: true,
      },
      { label: "Reproduce (representative cases)", value: NOT_RECORDED },
      {
        label: "Family coverage (AZ1)",
        value: `${FC.overviewNote} · ${FC.shortlistNote} (as of ${FC.asOf}; commit ${NOT_RECORDED})`,
        code: true,
      },
      { label: "Reproduce (family coverage)", value: FC.reproCommand, code: true },
      {
        label: "Evidence ceiling",
        value:
          "Descriptive snapshots only — the independence caution is not an inferential effective sample size, the family lens is an inventory rather than family-level inference, and representative cases are illustrative, not evidence.",
      },
    ],
  };
}

/**
 * Build the four-lane verification manifest from the page's existing Mission
 * G / Mission J query snapshots plus the canonical static constants.  Pure,
 * deterministic, and honest about pending / unavailable / unrecorded state.
 */
export function buildEvidenceVerificationManifest(
  missionG: EvidenceQuerySnapshot<MissionGEvidenceSummary>,
  missionJ: EvidenceQuerySnapshot<MissionJEvidenceSummary>,
): VerificationLane[] {
  return [acceptedLane(), missionGLane(missionG), missionJLane(missionJ), staticEvidenceLane()];
}

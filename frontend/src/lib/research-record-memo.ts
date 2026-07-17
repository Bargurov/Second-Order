/**
 * M2/N2 — canonical research-record memo
 * (schema second-order-research-record-v2).
 *
 * `buildResearchRecordMemo` is a PURE, deterministic builder: it composes one
 * portable Markdown rendering of the evidence record shown on the Evidence
 * Overview page from the same canonical static constants the page renders
 * (accepted-corpus, research-findings, effective-independent-evidence,
 * mechanism-family-evidence, representative-case-library) plus the Mission G,
 * Mission I, and Mission J contract payloads passed in as explicit lanes.  No
 * research number is retyped here; frozen Mission wording comes verbatim from
 * the contract fields.  The builder touches no window, document, network, DB,
 * provider, or wall clock — an optional export timestamp may be passed by the
 * caller and is labeled as export metadata only.  Output is LF-only and
 * byte-identical for identical input.
 *
 * Schema history: v1 carried 12 sections with the Mission G and Mission J
 * lanes only; v2 (N2) added the Mission I ordinary-period comparison ledger
 * between them — 13 sections exactly.  The identifier was bumped WITH the
 * section contract; the two never change independently.
 *
 * An unavailable lane is stated explicitly ("Mission G research record:
 * unavailable") — never silently omitted — and provenance fields the
 * canonical inputs do not record say "not recorded" rather than being
 * inferred.  The separate `downloadResearchRecordMemo` helper owns the
 * browser mechanics (Blob -> object URL -> temporary anchor -> revoke) behind
 * an injectable adapter so tests need no DOM.
 */
import type {
  MissionGEvidenceSummary,
  MissionIEvidenceSummary,
  MissionISourceKey,
  MissionJEvidenceSummary,
} from "./api";
import {
  ACCEPTED_CORPUS as AC,
  DENOMINATOR_LEDGER,
  FAMILY_COVERAGE as FC,
} from "./accepted-corpus";
import { RESEARCH_FINDINGS as F } from "./research-findings";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "./effective-independent-evidence";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "./mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "./representative-case-library";

export const RESEARCH_RECORD_SCHEMA_VERSION = "second-order-research-record-v2";
export const RESEARCH_RECORD_FILENAME = "second-order-research-record.md";
export const RESEARCH_RECORD_MIME_TYPE = "text/markdown;charset=utf-8";

/** One tracked evidence lane: the settled contract payload, or an explicit
 *  unavailable state that the memo must record rather than omit. */
export type MissionLane<T> = { available: true; data: T } | { available: false };

export interface ResearchRecordMemoInput {
  missionG: MissionLane<MissionGEvidenceSummary>;
  missionI: MissionLane<MissionIEvidenceSummary>;
  missionJ: MissionLane<MissionJEvidenceSummary>;
  /** Optional export timestamp supplied by the caller — export metadata
   *  only, never a research computation date. */
  exportedAt?: string;
}

// ---------------------------------------------------------------------------
// Query-snapshot mapping (kept pure so readiness / lane logic is testable
// without a DOM or React Query).
// ---------------------------------------------------------------------------

export interface EvidenceQuerySnapshot<T> {
  isPending: boolean;
  isError: boolean;
  data: T | undefined;
}

/** The export action is ready once ALL THREE contracts have settled —
 *  success or error — because an errored lane is exported as explicitly
 *  unavailable. */
export function researchRecordExportReady(
  missionG: EvidenceQuerySnapshot<unknown>,
  missionI: EvidenceQuerySnapshot<unknown>,
  missionJ: EvidenceQuerySnapshot<unknown>,
): boolean {
  return !missionG.isPending && !missionI.isPending && !missionJ.isPending;
}

function toLane<T>(query: EvidenceQuerySnapshot<T>): MissionLane<T> {
  if (!query.isError && query.data !== undefined) {
    return { available: true, data: query.data };
  }
  return { available: false };
}

/** Map the page's existing Mission G / I / J query results onto the memo
 *  input — the exact same payloads the page renders, no second fetch. */
export function researchRecordMemoInput(
  missionG: EvidenceQuerySnapshot<MissionGEvidenceSummary>,
  missionI: EvidenceQuerySnapshot<MissionIEvidenceSummary>,
  missionJ: EvidenceQuerySnapshot<MissionJEvidenceSummary>,
  exportedAt?: string,
): ResearchRecordMemoInput {
  return {
    missionG: toLane(missionG),
    missionI: toLane(missionI),
    missionJ: toLane(missionJ),
    exportedAt,
  };
}

// ---------------------------------------------------------------------------
// Pure Markdown builder
// ---------------------------------------------------------------------------

const NOT_RECORDED = "not recorded";

function identitySection(exportedAt?: string): string[] {
  const lines = [
    "## 1. Record identity",
    "",
    `- Schema: ${RESEARCH_RECORD_SCHEMA_VERSION}`,
    "- Evidence Overview route: /evidence",
  ];
  if (exportedAt !== undefined) {
    lines.push(
      `- Export timestamp (export metadata only, not a research computation date): ${exportedAt}`,
    );
  }
  lines.push(
    "- Research dates and source commits appear within their respective sections below.",
    "- This file is a browser export of the Evidence Overview record; the export itself is not a tracked publication.",
  );
  return lines;
}

function purposeSection(): string[] {
  return [
    "## 2. Purpose and permanent claim ceiling",
    "",
    "This record is a descriptive, event-driven, denominator-aware rendering of the evidence record shown on the Evidence Overview page. It is a portable copy of that record, not a new research publication and not a second interpretation of the research.",
    "",
    "Permanent claim ceiling — this record is:",
    "",
    "- not a recommendation;",
    "- not a prediction surface;",
    "- not evidence of alpha or tradeability;",
    "- not a claim of causality;",
    "- not a claim of single-event statistical significance.",
  ];
}

function denominatorSection(): string[] {
  return [
    "## 3. Canonical denominator ledger",
    "",
    `Each step is a different denominator answering a different question — not competing estimates of one number. Current accepted-lens snapshot as of ${AC.restatedOn}.`,
    "",
    "| # | Value | Denominator | Semantic note |",
    "| --- | --- | --- | --- |",
    ...DENOMINATOR_LEDGER.map(
      (row, i) => `| ${i + 1} | ${row.value} | ${row.label} | ${row.note} |`,
    ),
    "",
    "Staged candidates sit outside the accepted and FDR pools and never enter accepted denominators or claims. Event-study availability is a coverage denominator, not a significance claim; representative cases are illustrative, not evidence.",
  ];
}

function outcomeLedgersSection(): string[] {
  const horizons = F.t3aMulti.horizons
    .map((hz) => `${hz.h} support ${hz.support} vs null mean ${hz.nullMean}, 95% interval ${hz.ci}`)
    .join("; ");
  return [
    "## 4. Accepted outcome ledgers",
    "",
    `Two named outcome lenses over the same ${AC.trackRecordTotal} accepted track-record rows — same denominator, different semantics. Do not merge these two ledgers. No merged, averaged, or composite result exists in this record.`,
    "",
    "### Any-support / OR-rule ledger",
    "",
    `- Rule: ${AC.orRuleName} (db.compute_track_record)`,
    `- Denominator: ${AC.trackRecordTotal} accepted track-record rows`,
    `- Split: ${AC.anySupporting} any-supporting / ${AC.contradicted} contradicted / ${AC.unresolved} unresolved`,
    "- Tie / unresolved handling: no tie rule — a single supporting name is sufficient; rows with no scored directional evidence stay unresolved",
    "- Claim limitation: a descriptive evidence ledger, not predictive validation and not a success rate.",
    "",
    "### Directional-majority ledger",
    "",
    `- Rule: ${AC.directionalMajority.ruleName}`,
    `- Denominator: ${AC.trackRecordTotal} accepted track-record rows — the same rows under a different lens, never merged with the ledger above`,
    `- Split: ${AC.directionalMajority.validated} validated / ${AC.directionalMajority.contradicted} contradicted / ${AC.directionalMajority.unresolved} unresolved`,
    `- Tie / unresolved handling: ${AC.directionalMajority.tieNote}`,
    "- Claim limitation: the majority labels are the production scorer's vocabulary — evidence sufficiency, not a success verdict and not a claim about future events.",
    "",
    `Why the two distributions differ: ${AC.lensDivergenceNote}`,
    "",
    `### Baseline characterization — dated snapshot (as of ${F.asOf}, superseded denominators)`,
    "",
    "The T2/T3/T4 baseline characterization is a frozen snapshot of the then-current market-scored archive (pre-restatement, AP3b-era; the canonical denominators in section 3 supersede its corpus figures). Its findings stay visible:",
    "",
    `- Corpus snapshot: ${F.corpus.marketScored} market-scored / ${F.corpus.anySupporting} any-supporting / ${F.corpus.contradicted} contradicted / ${F.corpus.unresolved} unresolved; event-study ${F.corpus.eventStudyAvailable} available / ${F.corpus.eventStudyUnavailable} unavailable.`,
    `- T2A marginal-preserving baseline: observed validated ${F.t2aBaseline.observedValidated}; null mean ${F.t2aBaseline.nullMean}; 95% interval ${F.t2aBaseline.ci95}; verdict ${F.t2aBaseline.verdict}. ${F.t2aBaseline.interpretation}`,
    `- T2B primary-only AR-sign (benchmark ${F.t2bPrimary.benchmark}; ${F.t2bPrimary.eligiblePerHorizon} eligible observations per horizon): support 1d ${F.t2bPrimary.support["1d"]} / 5d ${F.t2bPrimary.support["5d"]} / 20d ${F.t2bPrimary.support["20d"]}; reliability: ${F.t2bPrimary.reliability}. ${F.t2bPrimary.reason}`,
    `- T3A multi-ticker AR-sign (${F.t3aMulti.eligibleObs} eligible ticker observations / ${F.t3aMulti.eligibleEvents} eligible events; predicted-up marginal ${F.t3aMulti.predictedUpMarginal}): ${horizons}. Verdict: ${F.t3aMulti.verdict}. ${F.t3aMulti.reliability}. ${F.t3aMulti.interpretation}`,
    `- T4A exposed-name AR coverage (repaired, V2C): beneficiary ${F.t4aCoverage.beneficiary} (${F.t4aCoverage.beneficiaryPct}); exposed / loser ${F.t4aCoverage.loser} (${F.t4aCoverage.loserPct}); total ${F.t4aCoverage.total} (${F.t4aCoverage.totalPct}). ${F.t4aCoverage.limitation}`,
  ];
}

function independenceSection(): string[] {
  return [
    "## 5. Independence caution",
    "",
    `The ${EIE.acceptedTrackRecordRows} accepted track-record rows group into ${EIE.clusterCount} descriptive market-story clusters under transparent same-date / same-primary-ticker-window / duplicate-link rules. The largest cluster holds ${EIE.largestClusterRows} rows and ${EIE.representativeCasesInLargest} / ${EIE.representativeCasesTotal} representative cases.`,
    "",
    `Read the support / contradiction / unresolved counts in section 4 as clustered evidence — a small number of market tapes observed many ways — not ${EIE.acceptedTrackRecordRows} separate market stories.`,
    "",
    "Descriptive independence-caution only — not an inferential effective sample size, score, rank, p-value, or FDR pool, and not a trading, prediction, or recommendation surface.",
  ];
}

const MISSION_G_UNAVAILABLE_LINE = "Mission G research record: unavailable";
const MISSION_I_UNAVAILABLE_LINE = "Mission I research record: unavailable";
const MISSION_J_UNAVAILABLE_LINE = "Mission J research record: unavailable";

/** Display labels for the seven Mission I publications, in contract order. */
const MISSION_I_SOURCE_ORDER: ReadonlyArray<[MissionISourceKey, string]> = [
  ["i0_protocol", "I0 protocol"],
  ["i1_universe", "I1 universe"],
  ["i2a_substrate", "I2A substrate"],
  ["i2b_memp", "I2B MEMP"],
  ["i2c_calibration", "I2C calibration"],
  ["i2c_falsifiers", "I2C falsifiers"],
  ["closeout", "Closeout"],
];

function missionGSection(lane: MissionLane<MissionGEvidenceSummary>): string[] {
  const head = ["## 6. Mission G — separate historical ledger", ""];
  if (!lane.available) {
    return [
      ...head,
      MISSION_G_UNAVAILABLE_LINE,
      "",
      "The /evidence/mission-g contract could not be loaded when this record was exported. No figures are reproduced in its place; the lane is recorded as unavailable rather than omitted. Mission G remains a separate historical ledger and is never pooled with the accepted track record.",
    ];
  }
  const g = lane.data;
  const opec = g.bounded_opec_association;
  const credit = g.credit_limitation;
  const g3b = g.failed_thesis_mechanism_comparability;
  const cov = g3b.classification_coverage_percent;
  const cases = g.representative_cases;
  const arts = g.source_artifacts;
  const perHorizon = opec.per_horizon
    .map(
      (h) =>
        `${h.horizon}d ${h.rho} (LOEO reversals ${h.loeo_sign_reversals}, LOYO reversals ${h.loyo_sign_reversals})`,
    )
    .join(" · ");
  return [
    ...head,
    `Contract: ${g.contract_version} (GET /evidence/mission-g; tracked research artifacts parsed at request time).`,
    "",
    "Research question: whether pre-event market state conditioned event reactions across two bounded historical universes — not whether the live archive shows above-baseline directional skill. A separate ledger, never pooled with the accepted track record.",
    "",
    "### Lanes and denominators",
    "",
    `- Accepted track record: ${g.lanes.accepted_track_record.count} — ${g.lanes.accepted_track_record.lane_note}.`,
    `- Historical ledger: ${g.lanes.historical.total} total — ${g.lanes.historical.fomc_frame_complete} FOMC frame-complete · ${g.lanes.historical.opec_designed_contrast} OPEC designed-contrast — ${g.lanes.historical.lane_note}.`,
    `- ${g.lanes.pooling_prohibition}`,
    "",
    "### Principal findings",
    "",
    `- ${g.main_result.headline}`,
    `- ${g.main_result.fomc_null.statement} (max |full-sample rho| ${g.main_result.fomc_null.max_abs_full_sample_rho})`,
    `- Sign reversals under uniform stress: ${g.stability.loeo_sign_reversals}/${g.stability.continuous_associations} leave-one-event-out · ${g.stability.loyo_sign_reversals}/${g.stability.continuous_associations} leave-one-calendar-year-out.`,
    `- ${g.stability.note}.`,
    "",
    "### One bounded exception",
    "",
    `- Axis: ${opec.axis} (lane ${opec.lane})`,
    `- Contract wording (verbatim): ${opec.wording}`,
    `- Per-horizon rho: ${perHorizon}`,
    `- Limitation: ${opec.confound_note}.`,
    "",
    "### Failed and incomplete evidence",
    "",
    `- HY OAS ${credit.available}/${credit.of} — era-bounded coverage (${credit.fomc_subset} FOMC / ${credit.opec_subset} OPEC), ${credit.status} lens only; ${credit.fragile_associations}/${credit.of_associations} of its associations flip sign under leave-one-out. ${credit.note}.`,
    `- ${g3b.statement} Classification coverage: ${cov.accepted_news_headlines}% accepted news headlines · ${cov.fomc_official_text}% FOMC official text · ${cov.opec_official_text}% OPEC official text.`,
    "",
    "### Representative cases (illustrations)",
    "",
    `- ${cases.unique_cases} state-anchored cases — ${cases.status}. ${cases.selection_note}.`,
    ...cases.cases.map(
      (c) => `- ${c.role}/${c.quantile} · ${c.lane} · ${c.state_axis} · ${c.candidate_id}`,
    ),
    "",
    "### Evidence class and sources",
    "",
    "- Evidence class: not recorded in the contract.",
    `- Source artifacts: ${arts.readout} · ${arts.stability} · ${arts.cases} · ${arts.promotion_proof} · ${arts.mechanism_attrition}`,
    `- Source commit / artifact hashes: ${NOT_RECORDED}`,
    `- Reproduction command: ${NOT_RECORDED}`,
    "",
    "#### Mission G non-claims (verbatim)",
    "",
    ...g.non_claims.map((nc) => `- ${nc}`),
  ];
}

function missionISection(lane: MissionLane<MissionIEvidenceSummary>): string[] {
  const head = ["## 7. Mission I — ordinary-period comparison ledger", ""];
  if (!lane.available) {
    return [
      ...head,
      MISSION_I_UNAVAILABLE_LINE,
      "",
      "The /evidence/mission-i contract could not be loaded when this record was exported. No figures are reproduced in its place; the lane is recorded as unavailable rather than omitted. Mission I remains a separate ordinary-period comparison ledger and is never pooled with Mission G, Mission J, or the accepted archive.",
    ];
  }
  const i = lane.data;
  const con = i.constitution;
  const fal = i.falsifiers;
  const knife = i.fragility.knife_edge;
  const fomc = i.universe.families[0];
  const opec = i.universe.families[1];
  if (fomc === undefined || opec === undefined) {
    return [
      ...head,
      MISSION_I_UNAVAILABLE_LINE,
      "",
      "The /evidence/mission-i payload did not carry the two frozen family lanes when this record was exported; the lane is recorded as unavailable rather than partially reproduced.",
    ];
  }
  const fomc20d = fomc.horizons.find((h) => h.horizon === "20d");
  const f6 = fal.f6_calibration_position;
  const affected = (cells: Array<{ cell_key: string; flips: number; of: number }>) =>
    cells.map((a) => `${a.cell_key} ${a.flips} / ${a.of}`).join(" · ");
  return [
    ...head,
    `Contract: ${i.contract_version} (GET /evidence/mission-i; tracked publications parsed at request time).`,
    "",
    `Research question (frozen, verbatim): ${con.frozen_question}`,
    "",
    `- Estimand: ${con.estimand.name} — ${con.estimand.definition.replace(/^- /, "")} Ordinary reference midpoint: ${con.estimand.ordinary_reference_midpoint}.`,
    `- ${con.family_pooling_prohibition}.`,
    `- ${i.calibration.interpretation_ceiling}`,
    "",
    "### Denominators and ordinary references (separate ledgers)",
    "",
    `- FOMC: ${fomc.study_event_n_available} event windows (${fomc.primary} vs ${fomc.market_benchmark} / ${fomc.sector_benchmark}).`,
    `- OPEC: ${opec.study_event_n_available} event windows (${opec.primary} vs ${opec.market_benchmark} / ${opec.sector_benchmark}).`,
    `- Primary cells: ${con.primary_cell_count} · falsifier families: ${Object.keys(fal.definitions).length}.`,
    "",
    "| Family | Horizon | Event N | Eligible ordinary reference N | Non-overlapping blocks | Status |",
    "| --- | --- | --- | --- | --- | --- |",
    ...i.universe.families.flatMap((family) =>
      family.horizons.map(
        (h) =>
          `| ${family.family} | ${h.horizon} | ${family.study_event_n_available} | ${h.reference_n_available} | ${h.non_overlapping_reference_n} | ${h.status} |`,
      ),
    ),
    "",
    `- Non-overlapping blocks: ${i.universe.blocks_note}`,
    ...(fomc20d?.limitation ? [`- FOMC 20d: ${fomc20d.limitation}`] : []),
    "",
    "### Twenty primary cells (frozen order)",
    "",
    "| # | Cell | Event N | Ref N | MEMP | Signed pct median | Calib pct | Direction | F6 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ...i.primary_cells.map(
      (c) =>
        `| ${c.cell} | ${c.cell_key} | ${c.event_n_available} | ${c.reference_n_available} | ${c.memp} | ${c.signed_percentile_median} | ${c.calibration_percentile} | ${c.state.memp_direction} | ${c.state.f6_position} |`,
    ),
    "",
    `- Signed-percentile disclosure: ${con.signed_percentile_disclosure.status} — ${con.signed_percentile_disclosure.disclaimers.join(" ")}`,
    "",
    "### Family × horizon readouts (verbatim)",
    "",
    ...i.family_horizon_readout.map((r) => `- ${r.family} ${r.horizon}: ${r.headline}`),
    "",
    "### Falsifier battery (six families, reported separately)",
    "",
    `- ${fal.battery_disclosure}.`,
    "",
    `- F1 — ${fal.definitions.f1}`,
    `- F1 result: ${fal.f1_loyo.flips_total} / ${fal.f1_loyo.runs_total} leave-out runs flip sign(MEMP − 0.5); affected cells: ${affected(fal.f1_loyo.affected_cells)}.`,
    `- F2 — ${fal.definitions.f2}`,
    `- F2 result: ${fal.f2_loeo.flips_total} / ${fal.f2_loeo.runs_total} leave-out runs flip sign(MEMP − 0.5); affected cells: ${affected(fal.f2_loeo.affected_cells)}. ${fal.f2_loeo.knife_edge_explanation}`,
    `- F3 — ${fal.definitions.f3}`,
    `- F3 result: ${fal.f3_overlap_decimation.sign_flips} / ${fal.f3_overlap_decimation.of_cells} primary-cell direction changes. ${fal.f3_overlap_decimation.reading} ${fal.f3_overlap_decimation.limitation}`,
    `- F4 — ${fal.definitions.f4}`,
    `- F4 result (above / at / below the 0.5 midpoint per family × horizon): ${fal.f4_cross_metric.map((r) => `${r.family} ${r.horizon} ${r.positive} / ${r.zero} / ${r.negative}`).join(" · ")}.`,
    `- F5 — ${fal.definitions.f5}`,
    `- F5 result (feasible-horizon agreement per family × metric): ${fal.f5_cross_horizon.map((r) => `${r.family} ${r.metric} ${r.agree ? "agree" : "disagree"}${r.caveat !== null ? " (see caveat)" : ""}`).join(" · ")}.`,
    ...fal.f5_cross_horizon
      .filter((r) => r.caveat !== null)
      .map((r) => `- F5 caveat (${r.family} ${r.metric}, verbatim): ${r.caveat}`),
    `- F6 — ${fal.definitions.f6}`,
    `- F6 result: ${f6.inside} inside · ${f6.outside} outside (${f6.outside_upper} upper · ${f6.outside_lower} lower). ${f6.limitation}`,
    "",
    "### Fragility",
    "",
    `- Knife edge: ${knife.cell_key} — MEMP ${knife.memp} · calibration ${knife.calibration_percentile} · LOYO ${knife.f1_loyo.flips} / ${knife.f1_loyo.runs} · LOEO ${knife.f2_loeo.flips} / ${knife.f2_loeo.runs}. ${knife.explanation}`,
    `- LOYO-affected cells: ${affected(i.fragility.loyo_affected_cells)}.`,
    "",
    "### Era-matched placement calibration",
    "",
    `- ${i.calibration.placements_per_group} placements per family × horizon group · fixed seed ${i.calibration.seed} · ${i.calibration.groups.map((g) => `${g.family} ${g.horizon} ${g.completed_placements}/${g.expected_placements}`).join(" · ")}.`,
    `- Method (verbatim): ${i.calibration.method}`,
    "",
    "### Whole-mission conclusion",
    "",
    `- Conclusion (verbatim): ${i.whole_mission_conclusion.statement}`,
    `- Clarifier (verbatim): ${i.whole_mission_conclusion.clarifier}`,
    "",
    "### Limitations (verbatim)",
    "",
    ...i.unresolved_or_limits.map((limit) => `- ${limit}`),
    "",
    "#### Mission I non-claims (verbatim)",
    "",
    ...i.non_claims.map((nc) => `- ${nc}`),
  ];
}

function missionJSection(lane: MissionLane<MissionJEvidenceSummary>): string[] {
  const head = ["## 8. Mission J — separate robustness and transmission ledger", ""];
  if (!lane.available) {
    return [
      ...head,
      MISSION_J_UNAVAILABLE_LINE,
      "",
      "The /evidence/mission-j contract could not be loaded when this record was exported. No figures are reproduced in its place; the lane is recorded as unavailable rather than omitted. Mission J remains a separate robustness and transmission ledger and is never pooled with Mission G or the accepted archive.",
    ];
  }
  const j = lane.data;
  const { j1b, j2, j3 } = j;
  const elevated = j1b.cells.filter((c) => c.node_state === "ELEVATED").length;
  const panels = j1b.panels
    .map((p) => `${p.role} (${p.members.join(", ")}; primary ${p.primary}): ${p.modifier}`)
    .join(" · ");
  const unavailableEvents = j1b.cells
    .filter((c) => (c.unavailable_events ?? []).length > 0)
    .map(
      (c) =>
        `cell ${c.cell} — ${(c.unavailable_events ?? [])
          .map(([date, reason]) => `${date}: ${reason}`)
          .join(", ")}`,
    )
    .join(" · ");
  const c2 = j2.collisions.c2;
  const diagnostics = j2.diagnostics;
  return [
    ...head,
    `Contract: ${j.contract_version} (GET /evidence/mission-j; tracked publications parsed at request time).`,
    "",
    "A hindsight-controlled robustness program over the completed FOMC 1d finding — a separate ledger, never pooled with Mission G or the accepted archive.",
    "",
    `- Publication status: ${j.provenance.publication_status}`,
    `- No-recompute statement: ${j.provenance.no_recompute_statement}`,
    "",
    `### J1B — asset and benchmark robustness (window ${j1b.window})`,
    "",
    `- ${elevated}/${j1b.cells.length} frozen cells at state ELEVATED.`,
    `- Panels at their published modifier: ${panels}`,
    `- Contextual curve-shape layer: ${j1b.contextual_2s10s.measurement} — ${j1b.contextual_2s10s.isolation_note} (published state ${j1b.contextual_2s10s.state}, as context only).`,
    `- Measurement-limited (verbatim): ${j1b.measurement_limited.statement}.`,
    `- Correlated views (verbatim): ${j1b.correlated_views_disclosure}.`,
    "",
    "| Cell | Measurement | Lens | Role | M | Events avail / att | Ref N | MEMP | Calib pct | State | LOYO | LOEO | F3 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ...j1b.cells.map(
      (c) =>
        `| ${c.cell} | ${c.measurement ?? c.metric ?? ""} | ${c.lens ?? c.window ?? ""} | ${c.role ?? ""} | ${c.m_class ?? ""} | ${c.available_event_n} / ${c.attempted_event_n} | ${c.reference_n} | ${c.memp} | ${c.calibration_percentile} | ${c.node_state} | ${c.loyo} | ${c.loeo} | ${c.f3_sign_flip ? "flip" : "no flip"} (${c.f3_reference_n} → ${c.f3_canonical_n}) |`,
    ),
    "",
    ...(unavailableEvents ? [`- Unavailable events: ${unavailableEvents}`, ""] : []),
    "#### J1B non-claims (verbatim)",
    "",
    ...j1b.non_claims.map((nc) => `- ${nc}`),
    "",
    `### J2 — pre-event timing challenge (window ${j2.window})`,
    "",
    "| Cell | Metric | State | MEMP | Calib pct | Events avail / att | Ref N | LOYO | LOEO | F3 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ...j2.state_bearing.map(
      (c) =>
        `| ${c.cell} | ${c.metric ?? c.measurement ?? ""} | ${c.node_state} | ${c.memp} | ${c.calibration_percentile} | ${c.available_event_n} / ${c.attempted_event_n} | ${c.reference_n} | ${c.loyo} | ${c.loeo} | ${c.f3_sign_flip ? "flip" : "no flip"} (${c.f3_reference_n} → ${c.f3_canonical_n}) |`,
    ),
    "",
    "Timing interpretation (verbatim from the contract):",
    "",
    ...j2.timing_interpretation.map((line) => `- ${line}`),
    "",
    `- Raw-cell fragility (${j2.raw_cell_fragility.metric}): LOYO ${j2.raw_cell_fragility.loyo} · LOEO ${j2.raw_cell_fragility.loeo} — ${j2.raw_cell_fragility.note}.`,
    ...(diagnostics[0] !== undefined
      ? [
          `- Descriptive diagnostics (${diagnostics[0].window}) — ${diagnostics[0].status_wording}:`,
          "",
          "| Diag | Metric | Window | Events avail / att | Median response | Median abs response | Direction |",
          "| --- | --- | --- | --- | --- | --- | --- |",
          ...diagnostics.map(
            (d) =>
              `| ${d.id} | ${d.metric} | ${d.window} | ${d.available_event_n} / ${d.attempted_event_n} | ${d.median_response} | ${d.median_abs_response} | ${d.direction} |`,
          ),
        ]
      : []),
    "",
    `### J2 — exact-window collision qualification (interval ${j2.collisions.interval})`,
    "",
    `- Primary denominator ${j2.collisions.primary_n} · known-register collision-free ${j2.collisions.collision_free_n}.`,
    `- C2 register ${c2.register} (${c2.register_dates} calendar dates): tags ${c2.tagged_n} of ${c2.of} events; C2-tagged subset (${c2.subset_n}): ${c2.subset_status}.`,
    `- C1 (${j2.collisions.c1.families}): ${j2.collisions.c1.status} — ${j2.collisions.c1.reason}`,
    `- FOMC self-collision invariant: minimum anchor spacing ${j2.collisions.fomc_self.min_anchor_spacing}, ${j2.collisions.fomc_self.violations} violations.`,
    `- Limitation: ${j2.collisions.limitation}.`,
    "",
    "### J3 — frozen mechanism and transmission readout",
    "",
    "Nodes (frozen roles):",
    "",
    ...j3.nodes.map((n) => {
      const panel =
        n.panel.length > 0
          ? ` Panel: ${n.panel
              .map(
                (m) =>
                  `${m.member}${m.primary ? " (primary, " : " ("}${m.m_class}): ${m.state}`,
              )
              .join(" · ")}${n.modifier ? `; ${n.modifier}` : ""}.`
          : "";
      return `- ${n.node} ${n.role} — reading ${n.reading} — ${n.rule_path}.${panel} Limitation: ${n.limitation}.`;
    }),
    "",
    "Edges (frozen adjudication):",
    "",
    ...j3.edges.map(
      (e) =>
        `- ${e.edge} ${e.from} → ${e.to}: ${e.state}. Upstream: ${e.upstream_reading} — ${e.upstream_path}. Downstream: ${e.downstream_state} (${e.downstream_m_class}; ${e.downstream_modifier}). ${e.rule_path}.`,
    ),
    "",
    `- Timing qualifier (verbatim): ${j3.timing_qualifier}`,
    `- Collision qualifier (verbatim): ${j3.collision_qualifier}`,
    "",
    "### Mission J claim limits and ceiling (verbatim)",
    "",
    ...j3.supports.map((s) => `- ${s}`),
    "",
    "Unresolved (verbatim):",
    "",
    ...j3.unresolved.map((u) => `- ${u}`),
    "",
    "#### Mission J non-claims (verbatim)",
    "",
    ...j3.non_claims.map((nc) => `- ${nc}`),
  ];
}

function familyInventorySection(): string[] {
  const overlayOnly = MFE.families
    .filter((f) => f.overlayOnly)
    .map((f) => f.family)
    .join(", ");
  const caseIds = MFE.families
    .map((f) => `${f.family} ${f.caseIds.join(", ")}`)
    .join(" · ");
  const grouping = F.mechanismFamilies.families
    .map((fam) =>
      fam.id === "none" ? `none / unclassified ${fam.count}` : `${fam.id} ${fam.count}`,
    )
    .join(" · ");
  const tier1 = FC.tier1.map((c) => `#${c.id} ${c.family} — ${c.label}`).join(" · ");
  return [
    "## 9. Mechanism-family evidence inventory",
    "",
    "Three family lenses exist on the Evidence Overview; they are different lenses over different denominators, not competing estimates of one count. Families appear in canonical order; no family is ranked.",
    "",
    "### Accepted track-record inventory (E2)",
    "",
    `- Lens: ${MFE.lens}`,
    `- Buckets: single-match ${MFE.buckets.singleMatch} · multi-match ${MFE.buckets.multiMatch} · unclassified ${MFE.buckets.unclassified} = ${MFE.buckets.sum}`,
    "",
    "| Family | n | S / C / U | Event-study | Sector hint | Flags |",
    "| --- | --- | --- | --- | --- | --- |",
    ...MFE.families.map((f) => {
      const flags =
        [f.overlayOnly ? "overlay-only" : "", f.thin ? "thin family" : ""]
          .filter(Boolean)
          .join(" · ") || "—";
      return `| ${f.family} | ${f.n} | ${f.s} / ${f.c} / ${f.u} | ${f.esAvailable} / ${f.esOf} | ${f.sector} | ${flags} |`;
    }),
    "",
    `- Illustrative case ids (representative of a family, not evidence for it): ${caseIds}`,
    `- Family-level limitations: the family lens is the tested headline overlay, not the stored mechanism_family taxonomy; overlay-only buckets (${overlayOnly}) sit outside the canonical taxonomy; multi-match (${MFE.buckets.multiMatch}) and unclassified (${MFE.buckets.unclassified}) rows stay visible, not absorbed; staged candidates are excluded from this lens; sectors are descriptive hints only (SPY stays the canonical benchmark); descriptive inventory — no family-level inference, no p-values, no FDR.`,
    "",
    `### Deterministic family grouping (T7B-A, dated snapshot as of ${F.asOf})`,
    "",
    `- ${F.mechanismFamilies.nonNone} / ${F.mechanismFamilies.scoredTotal} scored events carry a deterministic family: ${grouping}`,
    `- ${F.mechanismFamilies.label}`,
    `- ${F.mechanismFamilies.caveat}`,
    "",
    `### Accepted vs staged coverage (as of ${FC.asOf})`,
    "",
    `- Staged candidates (excluded from every accepted denominator): ${FC.stagedCandidates}`,
    `- Accepted family-labeled rows: ${FC.acceptedFamilyLabeled} — all curated observations (no thesis outcome)`,
    `- Untagged accepted rows: ${FC.untaggedAccepted} — a data limitation this record states rather than hides`,
    `- Staged-only families (zero accepted rows): ${FC.stagedOnlyFamilies}`,
    `- Tier-1 staged / no-paid shortlist: ${tier1}`,
    "- Staged candidates are not accepted evidence and never enter accepted denominators or claims.",
  ];
}

function representativeCasesSection(): string[] {
  return [
    "## 10. Representative-case context",
    "",
    `- ${RCL.totals.total} illustrative cases across ${RCL.totals.familiesTotal} mechanism families: ${RCL.totals.anchors} already-covered N1 anchors + ${RCL.totals.newNotes} newly proposed F1/F2 cases; event-study readout available for ${RCL.totals.eventStudyAvailable} / ${RCL.totals.eventStudyOf}; families represented ${RCL.totals.familiesRepresented} / ${RCL.totals.familiesTotal}.`,
    `- Selection framework: the frozen F1 selection rule (selection frozen @ ${RCL.sourceCommit}); outcomes restated ${RCL.outcomesRestatedOn} from the current archive; the selection itself never changes with outcomes. This is a different list from the app Case Library walkthrough, which is a separate editorial slate.`,
    "- Why cases are included: walkthrough depth for the family evidence. Cases are illustrative at n = 1 and are not proof; the outcome-frozen selection keeps supportive, contradicted and unresolved cases equally visible.",
    "",
    "| Case | Role | Family | Outcome | Event-study | Caveats |",
    "| --- | --- | --- | --- | --- | --- |",
    ...RCL.cases.map(
      (c) =>
        `| #${c.id} | ${c.role} | ${c.family} | ${c.outcome} | ${c.eventStudy ? "yes" : "no"} | ${c.caveats.length ? c.caveats.join(" · ") : "—"} |`,
    ),
    "",
    "- Readout availability is not the same as thesis support: outcome is thesis-direction scoring of the named tickers, while the event-study readout is the primary ticker vs SPY — a different lens (cases 29 and 38 share a readout but have opposite outcomes).",
  ];
}

function limitationsSection(input: ResearchRecordMemoInput): string[] {
  const missingReadouts = RCL.cases
    .filter((c) => !c.eventStudy)
    .map((c) => c.id)
    .join(", ");
  const plan = F.coverageRepairPlan;
  const fixability = plan.fixability
    .map((f) => `${f.id} ${f.count} (${f.fixable ? "fixable" : "not fixable"})`)
    .join(" · ");
  const lines = [
    "## 11. Data limitations and unresolved states",
    "",
    "Stated, not repaired. Only limitations present in the canonical inputs appear here.",
    "",
    `- Event-study coverage: ${AC.eventStudyAvailable} / ${AC.coverageDenominator} accepted coverage rows have a SPY-relative event-study readout — a coverage denominator, not a significance claim; the remainder has no computable readout.`,
    `- Single-event readout limits (benchmark ${F.methodology.benchmark}; horizons ${F.methodology.horizons}; estimation window ${F.methodology.estimationWindow} pre-event bars): ${F.methodology.limits.join(" ")}`,
    `- Correlated observations: the ${EIE.acceptedTrackRecordRows} accepted rows collapse into ${EIE.clusterCount} market-story clusters (section 5); events are date-clustered, not independent.`,
    `- Untagged accepted rows: ${FC.untaggedAccepted} accepted rows carry no mechanism_family label (section 8).`,
    `- Unresolved outcomes stay visible: ${AC.unresolved} unresolved under the any-support lens and ${AC.directionalMajority.unresolved} under the directional-majority lens (section 4); representative cases ${missingReadouts} have missing readouts (section 9).`,
    `- Coverage repair residue (V2C ${plan.status}): live exposed / loser AR coverage ${plan.liveLoser} and total ${plan.liveTotal} after promoting ${plan.rowsInserted} additive price-cache rows into live; residual missing units ${plan.remaining.units} (${plan.remaining.distinctSymbols} distinct symbols, ${plan.remaining.windows} windows) — ${fixability}.`,
    ...plan.notes.map((note) => `- ${note}`),
    `- Coverage-repair boundary: ${plan.nonClaim}`,
    '- Missing provenance: fields not canonically recorded are marked "not recorded" in section 12.',
  ];
  if (input.missionG.available) {
    const credit = input.missionG.data.credit_limitation;
    lines.push(
      `- Mission G: era-bounded ${credit.status} credit lane HY OAS ${credit.available}/${credit.of} (${credit.fragile_associations}/${credit.of_associations} associations flip sign under leave-one-out) and the failed mechanism-comparability axis (section 6).`,
    );
  } else {
    lines.push(
      "- Mission G research record: unavailable — its limitation and falsifier detail could not be exported (section 6).",
    );
  }
  if (input.missionI.available) {
    const iData = input.missionI.data;
    const knife = iData.fragility.knife_edge;
    const fomc20d = iData.universe.families[0]?.horizons.find(
      (h) => h.horizon === "20d",
    );
    lines.push(
      `- Mission I: FOMC 20d is structurally infeasible — no primary cells exist at that horizon${fomc20d?.limitation ? ` (${fomc20d.limitation})` : ""} (section 7).`,
      `- Mission I knife-edge fragility (${knife.cell_key}): LOYO ${knife.f1_loyo.flips} / ${knife.f1_loyo.runs} · LOEO ${knife.f2_loeo.flips} / ${knife.f2_loeo.runs} — ${knife.explanation}`,
    );
  } else {
    lines.push(
      "- Mission I research record: unavailable — its structural-unavailability and fragility detail could not be exported (section 7).",
    );
  }
  if (input.missionJ.available) {
    const j = input.missionJ.data;
    lines.push(
      `- Mission J measurement limitation: ${j.j1b.measurement_limited.statement}.`,
      `- Mission J correlated views: ${j.j1b.correlated_views_disclosure}.`,
      `- Mission J raw-cell fragility (${j.j2.raw_cell_fragility.metric}): LOYO ${j.j2.raw_cell_fragility.loyo} · LOEO ${j.j2.raw_cell_fragility.loeo} — ${j.j2.raw_cell_fragility.note}.`,
      `- Mission J collision limitation: ${j.j2.collisions.limitation}.`,
    );
  } else {
    lines.push(
      "- Mission J research record: unavailable — its measurement-limited and unresolved detail could not be exported (section 8).",
    );
  }
  return lines;
}

function provenanceSection(input: ResearchRecordMemoInput): string[] {
  const lines = [
    "## 12. Provenance and reproduction appendix",
    "",
    'Reproduction commands are recorded for reference only; nothing in this export executes them. Fields not canonically recorded say "not recorded".',
    "",
    "### Canonical denominators and accepted outcome ledgers",
    "",
    `- Source document: ${NOT_RECORDED} (dated snapshot restated read-only from the live archive)`,
    `- Source commit: ${NOT_RECORDED}`,
    `- Restatement date: ${AC.restatedOn}`,
    `- Reproduction (any-support OR-rule ledger): \`${AC.orRuleRepro}\``,
    `- Reproduction (directional-majority ledger): \`${AC.directionalMajority.repro}\``,
    "",
    "### Baseline characterization (T2/T3/T4)",
    "",
    `- Source document: ${NOT_RECORDED}`,
    `- Source commit: ${NOT_RECORDED}`,
    `- Snapshot date: ${F.asOf}`,
    `- Reproduction command: ${NOT_RECORDED}`,
    "",
    "### Effective independent evidence (K2)",
    "",
    `- Source document: ${EIE.sourceDoc}`,
    `- Source commit: ${EIE.sourceCommit}`,
    `- Reproduction: \`${EIE.reproCommand}\``,
    "",
    "### Mechanism-family evidence inventory (E1)",
    "",
    `- Source document: ${MFE.sourceDoc}`,
    `- Source commit: ${MFE.sourceCommit}`,
    `- Reproduction: \`${MFE.reproCommand}\``,
    "",
    "### Mechanism-family coverage (AZ1)",
    "",
    `- Source documents: ${FC.overviewNote} · ${FC.shortlistNote}`,
    `- Source commit: ${NOT_RECORDED}`,
    `- As-of date: ${FC.asOf}`,
    `- Reproduction: \`${FC.reproCommand}\``,
    "",
    "### Representative research set (F1/F2)",
    "",
    `- Source documents: ${RCL.sources[0]} · ${RCL.sources[1]}`,
    `- Source commit: ${RCL.sourceCommit}`,
    `- Outcomes restated: ${RCL.outcomesRestatedOn}`,
    `- Reproduction command: ${NOT_RECORDED}`,
    "",
    "### Mission G historical record",
    "",
  ];
  if (input.missionG.available) {
    const g = input.missionG.data;
    const arts = g.source_artifacts;
    lines.push(
      `- Contract: ${g.contract_version} via GET /evidence/mission-g (tracked artifacts parsed at request time)`,
      `- Source artifacts: ${arts.readout} · ${arts.stability} · ${arts.cases} · ${arts.promotion_proof} · ${arts.mechanism_attrition}`,
      `- Source commit: ${NOT_RECORDED}`,
      `- Artifact hashes: ${NOT_RECORDED}`,
      `- Computation / restatement date: ${NOT_RECORDED}`,
      `- Reproduction command: ${NOT_RECORDED}`,
    );
  } else {
    lines.push("- Mission G research record: unavailable — no provenance could be exported.");
  }
  lines.push("", "### Mission I published record", "");
  if (input.missionI.available) {
    const i = input.missionI.data;
    const versions = i.provenance.publication_versions;
    lines.push(
      `- Contract: ${i.contract_version} via GET /evidence/mission-i (tracked publications parsed at request time)`,
      ...MISSION_I_SOURCE_ORDER.map(([key, label]) => {
        const src = i.provenance.sources[key];
        return `- ${label} artifact: ${src.artifact} — sha256 ${src.sha256} · ${src.bytes} bytes`;
      }),
      `- Publication chain: ${i.provenance.publication_chain}`,
      `- Publication versions: ${MISSION_I_SOURCE_ORDER.filter(([key]) => key !== "closeout")
        .map(([key]) => versions[key as Exclude<MissionISourceKey, "closeout">])
        .join(" · ")}`,
      `- Reproduction (recorded in ${i.provenance.reproduction.source}): ${i.provenance.reproduction.commands.map((c) => `\`${c}\``).join(" · ")}`,
      `- Reproducibility limits: ${i.provenance.reproduction.reproducibility_limits}`,
      `- Computation dates: ${NOT_RECORDED}`,
      `- Execution commits: ${NOT_RECORDED}`,
    );
  } else {
    lines.push("- Mission I research record: unavailable — no provenance could be exported.");
  }
  lines.push("", "### Mission J published record", "");
  if (input.missionJ.available) {
    const j = input.missionJ.data;
    const src = j.provenance.sources;
    lines.push(
      `- Contract: ${j.contract_version} via GET /evidence/mission-j (tracked publications parsed at request time)`,
      `- J1B artifact: ${src.j1b.artifact} — sha256 ${src.j1b.sha256} · ${src.j1b.bytes} bytes`,
      `- J2 artifact: ${src.j2.artifact} — sha256 ${src.j2.sha256} · ${src.j2.bytes} bytes`,
      `- J3 artifact: ${src.j3.artifact} — sha256 ${src.j3.sha256} · ${src.j3.bytes} bytes`,
      `- Publication status: ${j.provenance.publication_status}`,
      `- Reproduction command: ${NOT_RECORDED}`,
    );
  } else {
    lines.push("- Mission J research record: unavailable — no provenance could be exported.");
  }
  return lines;
}

function finalNonClaimsSection(): string[] {
  return [
    "## 13. Final non-claims",
    "",
    "Standing non-claims of the evidence record:",
    "",
    ...F.nonClaims.map((line) => `- ${line}`),
    "",
    "This record does not establish causality, statistical significance,",
    "predictive performance, alpha, tradeability, or an investment recommendation.",
  ];
}

/** Build the canonical research-record memo. Pure and deterministic: same
 *  input, byte-identical LF Markdown. */
export function buildResearchRecordMemo(input: ResearchRecordMemoInput): string {
  const sections: string[][] = [
    ["# Second Order — Research Evidence Record"],
    identitySection(input.exportedAt),
    purposeSection(),
    denominatorSection(),
    outcomeLedgersSection(),
    independenceSection(),
    missionGSection(input.missionG),
    missionISection(input.missionI),
    missionJSection(input.missionJ),
    familyInventorySection(),
    representativeCasesSection(),
    limitationsSection(input),
    provenanceSection(input),
    finalNonClaimsSection(),
  ];
  return sections.map((lines) => lines.join("\n")).join("\n\n") + "\n";
}

// ---------------------------------------------------------------------------
// Browser download mechanics — separate helper, injectable for tests.
// ---------------------------------------------------------------------------

export interface MemoDownloadAnchor {
  href: string;
  download: string;
  click(): void;
}

export interface MemoDownloadAdapter {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
  createAnchor(): MemoDownloadAnchor;
  mount(anchor: MemoDownloadAnchor): void;
  unmount(anchor: MemoDownloadAnchor): void;
}

function browserDownloadAdapter(): MemoDownloadAdapter {
  return {
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    createAnchor: () => document.createElement("a"),
    mount: (anchor) => document.body.appendChild(anchor as HTMLAnchorElement),
    unmount: (anchor) => document.body.removeChild(anchor as HTMLAnchorElement),
  };
}

/**
 * Trigger a browser download of the built memo: one UTF-8 Markdown Blob, one
 * object URL, one temporary anchor — the anchor is removed and the URL is
 * revoked even if the click throws, so repeated clicks can never leak.
 */
export function downloadResearchRecordMemo(
  markdown: string,
  filename: string = RESEARCH_RECORD_FILENAME,
  adapter: MemoDownloadAdapter = browserDownloadAdapter(),
): void {
  const url = adapter.createObjectURL(
    new Blob([markdown], { type: RESEARCH_RECORD_MIME_TYPE }),
  );
  try {
    const anchor = adapter.createAnchor();
    anchor.href = url;
    anchor.download = filename;
    adapter.mount(anchor);
    try {
      anchor.click();
    } finally {
      adapter.unmount(anchor);
    }
  } finally {
    adapter.revokeObjectURL(url);
  }
}

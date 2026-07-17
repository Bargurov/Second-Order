/**
 * Current accepted-corpus denominators — the single source shared by the Case
 * Library and Evidence Overview so the two surfaces cannot drift apart again.
 *
 * These are a DATED snapshot of a derivable truth, not the source of truth: the
 * read-only report scripts (`scripts/stat_validation_readiness_report.py`,
 * `scripts/track_record_report.py` (the `db.compute_track_record` ledger),
 * `scripts/event_study_coverage_report.py`,
 * `scripts/validation_status_calibration_report.py`) recompute every figure
 * from whatever `events.db` is present. The numbers below reflect the
 * maintainer's local archive as of `restatedOn`; a clean clone (empty archive)
 * computes zero. Re-derive and bump `restatedOn` when the archive moves.
 *
 * The 2026-07-11 restatement follows the directional-evidence recovery (eight
 * accepted events whose 5d directions were back-computed from already-cached
 * bars) plus natural window maturation since the 2026-06-09 AP3b restatement.
 * The AP3b exclusion stands: 71 synthetic/test seed rows are flagged in the
 * `event_hygiene` sidecar (`override_class = 'synthetic_seed'`) and EXCLUDED
 * from the accepted-corpus denominators while remaining in the archive
 * (keep-and-flag, never deleted).
 *
 * TWO OUTCOME LENSES, never merged, over the same 86 accepted rows:
 *   1. Any-support OR-rule (`db.compute_track_record`): one supporting
 *      directional name puts the event in the any-supporting bucket. A
 *      descriptive ledger — not a majority vote, not predictive validation.
 *   2. Directional-majority rule (`validation_status_v2`): supporting vs
 *      contradicting names; supporting majority -> validated, ties and
 *      contradicting majorities -> contradicted under the frozen current rule,
 *      no directional evidence -> unresolved after the pending window.
 *      Calibrated for evidence sufficiency only (KEEP_CURRENT_RULE); no
 *      predictive-accuracy target was available.
 */
export const ACCEPTED_CORPUS = {
  /** Date the denominators below were last restated from the live archive. */
  restatedOn: "2026-07-11",
  /** Total events saved in the archive (incl. flagged seeds + staged/pending). */
  savedEvents: 180,
  /** Thesis events in the accepted track-record denominator (synthetic excluded). */
  trackRecordTotal: 86,
  /** Lens 1 — Any-support OR-rule outcome split (db.compute_track_record). */
  orRuleName: "Any-support OR-rule",
  anySupporting: 59,
  contradicted: 14,
  unresolved: 13,
  /** Read-only reproduction path for the OR-rule ledger — a mode=ro SQLite
   *  report that never creates, migrates, or renames the source archive
   *  (tests/test_track_record_reproduction_safety.py). */
  orRuleRepro:
    "python scripts/track_record_report.py --db-path events.db --json",
  /** Lens 2 — Directional-majority rule (validation_status_v2) over the SAME 86 rows. */
  directionalMajority: {
    ruleName: "Directional-majority rule (validation_status_v2)",
    validated: 29,
    contradicted: 44,
    unresolved: 13,
    tieNote:
      "ties (supports == contradicts) count as contradicted under the frozen current rule",
    repro:
      "python scripts/validation_status_calibration_report.py --db-path events.db",
  },
  /** Why the two distributions differ (one sentence, shown next to both ledgers). */
  lensDivergenceNote:
    "One supporting name is enough under the OR-rule, while the directional-majority rule weighs supporting against contradicting names and counts ties as contradicted — that is why the two distributions differ.",
  /** Analysis / coverage denominator (synthetic excluded). */
  coverageDenominator: 94,
  /** Realized accepted rows with a computable event-study readout (re-verified 2026-07-11). */
  eventStudyAvailableRealized: 49,
  /**
   * Accepted coverage rows with a computable SPY-relative event-study readout —
   * the readiness `event_study_available` status count, 78 of the 94 coverage
   * denominator (accepted lens). A coverage figure, NOT a significance claim and
   * distinct from `eventStudyAvailableRealized` (49, rows with a stored readout).
   * Re-derive read-only:
   *   python scripts/stat_validation_readiness_report.py --db-path events.db --json --lens accepted
   *     -> compute_readiness.event_study_compute_ready_count / total_events (94)
   *   python scripts/event_study_coverage_report.py
   */
  eventStudyAvailable: 78,
  /** Synthetic/test seed rows flagged in event_hygiene and excluded (kept in archive). */
  syntheticSeedFlagged: 71,
} as const;

/**
 * Mechanism-family coverage — accepted vs staged separation (AY1/AZ1).
 *
 * Same contract as ACCEPTED_CORPUS above: a DATED snapshot of a derivable
 * truth. `scripts/mechanism_family_overview_report.py` recomputes every figure
 * read-only from whatever `events.db` is present; re-derive and bump `asOf`
 * when the archive moves. Staged `z1a_candidate_pack` rows are review staging
 * — never accepted evidence, never inside accepted denominators.
 */
export const FAMILY_COVERAGE = {
  /** Date the family-coverage figures below were derived from the live archive. */
  asOf: "2026-06-10",
  /** Staged candidates (excluded from every accepted denominator). */
  stagedCandidates: 13,
  /** Accepted family-labeled rows — all curated observations (no thesis outcome). */
  acceptedFamilyLabeled: "tariff 4 · sanction 4",
  /** Accepted rows with no mechanism_family label (limitation bucket). */
  untaggedAccepted: 86,
  /** Staged-only families (zero accepted rows) with staged counts. */
  stagedOnlyFamilies: "regulation 5 · labor_inflation 2 · industrial_policy 2",
  /** Tier-1 staged/no-paid shortlist (stats/STAGED_CANDIDATE_SHORTLIST.md). */
  tier1: [
    { id: 303, family: "regulation", label: "DOJ v Apple — conduct antitrust" },
    { id: 304, family: "regulation", label: "DOJ v Google ad-tech — structural antitrust" },
    { id: 313, family: "labor_inflation", label: "UAW strike — production / wage-cost shock" },
  ],
  /** Read-only reproduce command for every figure in this block. */
  reproCommand:
    "python scripts/mechanism_family_overview_report.py --db-path events.db --json",
  overviewNote: "stats/MECHANISM_FAMILY_OVERVIEW.md",
  shortlistNote: "stats/STAGED_CANDIDATE_SHORTLIST.md",
  /** Baseline commit RECORDED in the shortlist decision log ("main /
   *  origin/main expected at `4dab1a1`" at time of review) — the
   *  shortlist's recorded pin, not a claim about the overview map. */
  shortlistBaselineCommit: "4dab1a1",
} as const;

/**
 * D1 — the canonical denominator funnel, shared by the Evidence Overview
 * page and the research-record memo export (M2) so the two renderings can
 * never drift apart.  Every figure is composed from the constants above (no
 * number is retyped); each step is a DIFFERENT denominator answering a
 * DIFFERENT question — not a competing estimate of one number.
 */
export const DENOMINATOR_LEDGER: ReadonlyArray<{
  value: string;
  label: string;
  note: string;
}> = [
  {
    value: String(ACCEPTED_CORPUS.savedEvents),
    label: "archive rows",
    note: "Full local archive — every saved event, including flagged seeds and staged / pending rows.",
  },
  {
    value: String(ACCEPTED_CORPUS.coverageDenominator),
    label: "accepted coverage rows",
    note: "Accepted rows eligible for coverage / event-date reporting.",
  },
  {
    value: String(ACCEPTED_CORPUS.trackRecordTotal),
    label: "accepted track-record rows",
    note: "Accepted rows used for support / contradiction / unresolved accounting.",
  },
  {
    value: `${ACCEPTED_CORPUS.eventStudyAvailable} / ${ACCEPTED_CORPUS.coverageDenominator}`,
    label: "event-study available",
    note: "Accepted coverage rows with a SPY-relative event-study readout — a coverage denominator, not a significance claim.",
  },
  {
    value: String(FAMILY_COVERAGE.stagedCandidates),
    label: "staged candidates",
    note: "Outside the accepted and FDR pools; never merged into accepted claims.",
  },
];

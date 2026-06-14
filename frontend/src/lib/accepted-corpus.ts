/**
 * Current accepted-corpus denominators — the single source shared by the Case
 * Library and Evidence Overview so the two surfaces cannot drift apart again.
 *
 * These are a DATED snapshot of a derivable truth, not the source of truth: the
 * read-only report scripts (`scripts/stat_validation_readiness_report.py`,
 * `db.compute_track_record`, `scripts/event_study_coverage_report.py`) recompute
 * every figure from whatever `events.db` is present. The numbers below reflect
 * the maintainer's local archive as of `restatedOn`; a clean clone (empty
 * archive) computes zero. Re-derive and bump `restatedOn` when the archive moves.
 *
 * `restatedOn` marks the AP3b restatement: 71 synthetic/test seed rows were
 * flagged in the `event_hygiene` sidecar (`override_class = 'synthetic_seed'`)
 * and EXCLUDED from the accepted-corpus denominators while remaining in the
 * archive (keep-and-flag, never deleted).
 */
export const ACCEPTED_CORPUS = {
  /** Date the denominators below were last restated from the live archive. */
  restatedOn: "2026-06-09",
  /** Total events saved in the archive (incl. flagged seeds + staged/pending). */
  savedEvents: 180,
  /** Thesis events in the accepted track-record denominator (synthetic excluded). */
  trackRecordTotal: 86,
  /** Accepted track-record outcome split (compute_track_record). */
  anySupporting: 46,
  contradicted: 8,
  unresolved: 32,
  /** Analysis / coverage denominator (synthetic excluded). */
  coverageDenominator: 94,
  /** Realized accepted rows with a computable event-study readout. */
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
} as const;

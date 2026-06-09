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
  /** Synthetic/test seed rows flagged in event_hygiene and excluded (kept in archive). */
  syntheticSeedFlagged: 71,
} as const;

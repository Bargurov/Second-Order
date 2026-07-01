/**
 * Effective independent evidence (K3B) — a frontend SURFACE of the read-only
 * K2 report. These figures are NOT recomputed in the browser and add no new
 * analysis; they are a static, typed snapshot of K2's output.
 *
 * Source of truth (re-derive read-only — a clean clone computes its own):
 *   stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md
 *   source commit: 8d247ea
 *   python scripts/effective_independent_evidence_report.py --db-path events.db --json
 *
 * The K2 report groups the 86 accepted track-record rows into descriptive
 * market-story clusters (same event date / same primary ticker within a 20-day
 * window / explicit duplicate links). It is a descriptive independence-caution
 * layer only: not an inferential effective sample size, score, rank, p-value,
 * or FDR pool, and not a trading, prediction, or recommendation surface.
 */
export const EFFECTIVE_INDEPENDENT_EVIDENCE = {
  sourceCommit: "8d247ea",
  sourceDoc: "stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md",
  reproCommand:
    "python scripts/effective_independent_evidence_report.py --db-path events.db --json",
  /** Nominal accepted track-record rows (the K2 lens; = the ledger's 86). */
  acceptedTrackRecordRows: 86,
  /** Descriptive market-story clusters the 86 rows group into. */
  clusterCount: 5,
  /** Rows in the single largest cluster (c01). */
  largestClusterRows: 81,
  /** Representative walkthrough cases that fall inside the largest cluster. */
  representativeCasesInLargest: 14,
  representativeCasesTotal: 15,
} as const;

/**
 * Mechanism-family evidence inventory (E2) — a frontend SURFACE of the
 * read-only E1 report. These figures are NOT recomputed in the browser and add
 * no new analysis; they are a static, typed snapshot of E1's output.
 *
 * Source of truth (re-derive read-only — a clean clone computes its own):
 *   stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md
 *   source commit: 77354e9
 *   python scripts/mechanism_family_evidence_inventory.py --db-path events.db --json
 *
 * Family lens: the tested J1 headline overlay over the 86 accepted thesis rows
 * (every thesis row is stored mechanism_family='none', so the headline overlay
 * is the only lens with family structure) — NOT the stored taxonomy. Per-family
 * event-study coverage is k-of-n on the 86 track-record lens (distinct from the
 * global 78/94 coverage lens in the denominator ledger). Descriptive inventory
 * only: no family-level inference, no p-values, no FDR, SPY stays canonical and
 * sectors are descriptive hints only.
 *
 * `s` / `c` / `u` = support / contradiction / unresolved counts under the
 * canonical any_support rule, applied descriptively per event.
 */
export const MECHANISM_FAMILY_EVIDENCE = {
  sourceCommit: "77354e9",
  sourceDoc: "stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md",
  reproCommand:
    "python scripts/mechanism_family_evidence_inventory.py --db-path events.db --json",
  /** The lens the family rows live on. */
  lens: "accepted track-record lens (86 rows) grouped by the tested headline overlay",
  /** Single-match + multi-match + unclassified = the 86 track-record rows. */
  buckets: { singleMatch: 52, multiMatch: 16, unclassified: 18, sum: 86 },
  /** Six families with at least one accepted thesis row. Ordered by accepted n. */
  families: [
    {
      family: "supply_shock",
      n: 20,
      s: 11, c: 3, u: 6,
      esAvailable: 20, esOf: 20,
      sector: "energy",
      overlayOnly: false,
      thin: false,
      caseIds: [29, 38, 210],
    },
    {
      family: "geopolitical_conflict_context",
      n: 11,
      s: 7, c: 2, u: 2,
      esAvailable: 10, esOf: 11,
      sector: "energy · industrials",
      overlayOnly: true,
      thin: false,
      caseIds: [7, 30, 232],
    },
    {
      family: "tariff",
      n: 11,
      s: 5, c: 0, u: 6,
      esAvailable: 8, esOf: 11,
      sector: "consumer_discretionary · industrials",
      overlayOnly: false,
      thin: false,
      caseIds: [1, 80, 212],
    },
    {
      family: "sanction",
      n: 4,
      s: 0, c: 0, u: 4,
      esAvailable: 1, esOf: 4,
      sector: "no confident sector match",
      overlayOnly: false,
      thin: true,
      caseIds: [153, 154, 211],
    },
    {
      family: "ceasefire_deescalation",
      n: 3,
      s: 2, c: 0, u: 1,
      esAvailable: 2, esOf: 3,
      sector: "energy",
      overlayOnly: false,
      thin: true,
      caseIds: [66, 71, 160],
    },
    {
      family: "monetary_policy_or_rates",
      n: 3,
      s: 1, c: 0, u: 2,
      esAvailable: 2, esOf: 3,
      sector: "financials",
      overlayOnly: true,
      thin: true,
      caseIds: [46, 231, 239],
    },
  ],
} as const;

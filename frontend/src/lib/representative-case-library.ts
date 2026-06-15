/**
 * Representative case library (F3) — a frontend SURFACE of the F1/F2 reports.
 * NOT recomputed in the browser, no network; a static typed snapshot.
 *
 * Source of truth (re-derive read-only):
 *   stats/REPRESENTATIVE_CASE_EXPANSION.md   (F1 — the 15-case selection)
 *   stats/EXPANDED_CASE_NOTES.md             (F2 — notes for the 9 new cases)
 *   source commit: 399aa8d
 *   python scripts/representative_case_expansion_report.py --db-path events.db --json
 *   python scripts/expanded_case_notes_report.py --db-path events.db --json
 *
 * The library is 15 illustrative cases: 6 already-covered N1 anchors (kept in
 * the existing transmission walkthrough, not rewritten) + 9 newly proposed F1
 * cases with expanded F2 notes. Outcome is thesis-direction scoring of the named
 * tickers (support / contradiction / unresolved); event-study availability is a
 * separate lens (primary ticker vs SPY). Illustrative only — not evidence and
 * not family-level inference.
 */
export const REPRESENTATIVE_CASE_LIBRARY = {
  sourceCommit: "399aa8d",
  sources: [
    "stats/REPRESENTATIVE_CASE_EXPANSION.md",
    "stats/EXPANDED_CASE_NOTES.md",
  ],
  totals: {
    total: 15,
    anchors: 6,
    newNotes: 9,
    eventStudyAvailable: 12,
    eventStudyOf: 15,
    familiesRepresented: 6,
    familiesTotal: 6,
  },
  /** Anchors first (already-covered N1), then the 9 newly proposed cases. */
  cases: [
    { id: 1, role: "anchor", family: "tariff", outcome: "support", eventStudy: true, caveats: [] },
    { id: 46, role: "anchor", family: "monetary_policy_or_rates", outcome: "support", eventStudy: true, caveats: ["overlay-only"] },
    { id: 61, role: "anchor", family: "geopolitical_conflict_context", outcome: "contradiction", eventStudy: true, caveats: ["overlay-only"] },
    { id: 66, role: "anchor", family: "ceasefire_deescalation", outcome: "support", eventStudy: true, caveats: ["thin family"] },
    { id: 210, role: "anchor", family: "supply_shock", outcome: "unresolved", eventStudy: true, caveats: [] },
    { id: 211, role: "anchor", family: "sanction", outcome: "unresolved", eventStudy: true, caveats: ["thin family"] },
    { id: 7, role: "new", family: "geopolitical_conflict_context", outcome: "support", eventStudy: true, caveats: ["overlay-only"] },
    { id: 29, role: "new", family: "supply_shock", outcome: "contradiction", eventStudy: true, caveats: ["shared XLE / date cluster"] },
    { id: 38, role: "new", family: "supply_shock", outcome: "support", eventStudy: true, caveats: ["shared XLE / date cluster"] },
    { id: 71, role: "new", family: "ceasefire_deescalation", outcome: "support", eventStudy: true, caveats: ["thin family"] },
    { id: 153, role: "new", family: "sanction", outcome: "unresolved", eventStudy: false, caveats: ["thin family", "missing readout"] },
    { id: 154, role: "new", family: "sanction", outcome: "unresolved", eventStudy: false, caveats: ["thin family", "missing readout"] },
    { id: 160, role: "new", family: "ceasefire_deescalation", outcome: "unresolved", eventStudy: false, caveats: ["thin family", "missing readout"] },
    { id: 212, role: "new", family: "tariff", outcome: "unresolved", eventStudy: true, caveats: ["clean event-date anchor"] },
    { id: 239, role: "new", family: "monetary_policy_or_rates", outcome: "unresolved", eventStudy: true, caveats: ["overlay-only", "thin family"] },
  ],
} as const;

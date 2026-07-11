/**
 * ACCEPTED_CORPUS — the dated accepted-corpus snapshot must match the
 * post-recovery archive ledgers and carry BOTH outcome lenses under explicit
 * names (reconciliation, 2026-07-11).
 *
 * The two ledgers protected here were recomputed read-only at task entry from
 * the canonical paths the snapshot itself names:
 *   - Any-support OR-rule:      db.compute_track_record()          -> 59 / 14 / 13 of 86
 *   - Directional-majority rule: validation_status_v2 (production   -> 29 / 44 / 13 of 86
 *     scorer via scripts/validation_status_calibration_report.py)
 * These are DIFFERENT semantics over the same 86 rows and are never merged.
 */
import { describe, expect, it } from "vitest";

import { ACCEPTED_CORPUS } from "../accepted-corpus";

describe("ACCEPTED_CORPUS — post-recovery restatement (2026-07-11)", () => {
  it("is restated on the reconciliation date, not the pre-recovery date", () => {
    expect(ACCEPTED_CORPUS.restatedOn).toBe("2026-07-11");
  });

  it("carries the recomputed Any-support OR-rule split (59 / 14 / 13)", () => {
    expect(ACCEPTED_CORPUS.anySupporting).toBe(59);
    expect(ACCEPTED_CORPUS.contradicted).toBe(14);
    expect(ACCEPTED_CORPUS.unresolved).toBe(13);
  });

  it("keeps the OR-rule split summing to the accepted denominator (86)", () => {
    expect(
      ACCEPTED_CORPUS.anySupporting +
        ACCEPTED_CORPUS.contradicted +
        ACCEPTED_CORPUS.unresolved,
    ).toBe(ACCEPTED_CORPUS.trackRecordTotal);
    expect(ACCEPTED_CORPUS.trackRecordTotal).toBe(86);
  });

  it("names the OR-rule lens explicitly", () => {
    expect(ACCEPTED_CORPUS.orRuleName).toBe("Any-support OR-rule");
  });

  it("carries the directional-majority ledger under its explicit rule name", () => {
    const dm = ACCEPTED_CORPUS.directionalMajority;
    expect(dm?.ruleName).toBe("Directional-majority rule (validation_status_v2)");
    expect(dm?.validated).toBe(29);
    expect(dm?.contradicted).toBe(44);
    expect(dm?.unresolved).toBe(13);
  });

  it("keeps the majority-rule split summing to the same 86 denominator (never merged)", () => {
    const dm = ACCEPTED_CORPUS.directionalMajority;
    expect((dm?.validated ?? 0) + (dm?.contradicted ?? 0) + (dm?.unresolved ?? 0)).toBe(
      ACCEPTED_CORPUS.trackRecordTotal,
    );
  });

  it("states the tie rule of the frozen current majority rule", () => {
    const tieNote = ACCEPTED_CORPUS.directionalMajority?.tieNote ?? "";
    expect(tieNote.toLowerCase()).toContain("ties");
    expect(tieNote.toLowerCase()).toContain("contradicted");
  });

  it("explains in one sentence why the two distributions differ", () => {
    const note = (ACCEPTED_CORPUS.lensDivergenceNote ?? "").toLowerCase();
    expect(note).toContain("one supporting name is enough");
    expect(note).toContain("majority");
  });

  it("carries exact read-only reproduction paths for both ledgers", () => {
    expect(ACCEPTED_CORPUS.orRuleRepro ?? "").toContain("compute_track_record");
    expect(ACCEPTED_CORPUS.directionalMajority?.repro ?? "").toContain(
      "validation_status_calibration_report.py",
    );
  });

  it("keeps the unchanged funnel figures (re-verified, not retyped)", () => {
    expect(ACCEPTED_CORPUS.savedEvents).toBe(180);
    expect(ACCEPTED_CORPUS.coverageDenominator).toBe(94);
    expect(ACCEPTED_CORPUS.eventStudyAvailable).toBe(78);
    expect(ACCEPTED_CORPUS.eventStudyAvailableRealized).toBe(49);
    expect(ACCEPTED_CORPUS.syntheticSeedFlagged).toBe(71);
  });
});
